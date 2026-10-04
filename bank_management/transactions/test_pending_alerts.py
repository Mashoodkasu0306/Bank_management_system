from django.contrib.auth.models import User
from django.urls import reverse

from notifications.models import Notification
from services.tests import make_employee
from transactions.models import Transaction
from transactions.tests import TransactionTestBase


class PendingTransactionAlertsTestCase(TransactionTestBase):
    def setUp(self):
        super().setUp()
        # emp1 (from the base class) has no department, so he should get nothing.
        make_employee(self.branch, username="txnguy", department="TRANSACTIONS")
        make_employee(self.branch, username="kycguy", department="KYC")
        make_employee(self.branch, username="loanguy", department="LOANS")
        User.objects.create_superuser(username="boss", password="x", email="boss@test.com")

    def over_limit_deposit(self):
        self.login_staff()
        self.client.post(reverse("deposit"), {
            "account_no": self.acc_a.account_no, "amount": "60000.00",
        })
        return Transaction.objects.filter(to_account=self.acc_a, status="PENDING").latest("id")

    def alerts(self, txn):
        return Notification.objects.filter(related_type="TRANSACTION", related_id=txn.id)

    def decide(self, txn, action):
        self.client.post(reverse("approve_transaction", args=[txn.id]), {"action": action})

    def test_pending_deposit_alerts_only_transactions_department_and_admin(self):
        txn = self.over_limit_deposit()
        who = set(self.alerts(txn).values_list("recipient__username", flat=True))
        self.assertEqual(who, {"txnguy", "boss"})

    def test_alert_links_to_pending_approvals(self):
        txn = self.over_limit_deposit()
        alert = self.alerts(txn).get(recipient__username="txnguy")
        self.assertEqual(alert.category, "TRANSACTION")
        self.assertEqual(alert.link, reverse("pending_transactions"))

    def test_normal_deposit_sends_no_staff_alert(self):
        self.login_staff()
        self.client.post(reverse("deposit"), {
            "account_no": self.acc_a.account_no, "amount": "1500.00",
        })
        self.assertEqual(Notification.objects.filter(related_type="TRANSACTION").count(), 0)

    def test_approving_marks_the_alerts_read(self):
        txn = self.over_limit_deposit()
        self.decide(txn, "approve")
        txn.refresh_from_db()
        self.assertEqual(txn.status, "SUCCESS")
        self.assertEqual(self.alerts(txn).filter(is_read=False).count(), 0)

    def test_rejecting_marks_the_alerts_read(self):
        txn = self.over_limit_deposit()
        self.decide(txn, "reject")
        txn.refresh_from_db()
        self.assertEqual(txn.status, "FAILED")
        self.assertEqual(self.alerts(txn).filter(is_read=False).count(), 0)

    def test_deciding_one_transaction_leaves_other_alerts_unread(self):
        first = self.over_limit_deposit()
        second = self.over_limit_deposit()
        self.decide(first, "approve")
        self.assertEqual(self.alerts(first).filter(is_read=False).count(), 0)
        self.assertEqual(self.alerts(second).filter(is_read=False).count(), 2)  # txnguy + boss
