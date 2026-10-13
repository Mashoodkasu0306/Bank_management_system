from decimal import Decimal

from django.urls import reverse

from audit.models import Actions, AuditLog
from transactions.models import Transaction
from services.tests import make_verified_kyc
from transactions.tests import TransactionTestBase


class CategoryOnTransferTests(TransactionTestBase):
    def setUp(self):
        super().setUp()
        make_verified_kyc(self.customer)

    def send(self, **extra):
        data = {
            "from_account_no": self.acc_a.account_no,
            "to_account_no": self.acc_b.account_no,
            "amount": "100.00",
            "mode_of_transaction": "NETBANKING",
        }
        data.update(extra)
        self.login_customer()
        self.client.post(reverse("customer_transfer"), data)
        return Transaction.objects.filter(from_account=self.acc_a).latest("id")

    def test_chosen_category_is_saved(self):
        txn = self.send(category="FOOD")
        self.assertEqual(txn.status, "SUCCESS")
        self.assertEqual(txn.category, "FOOD")

    def test_unknown_category_becomes_other(self):
        self.assertEqual(self.send(category="PIRATES").category, "OTHER")

    def test_missing_category_becomes_other(self):
        self.assertEqual(self.send().category, "OTHER")

    def test_transfer_form_shows_the_category_dropdown(self):
        self.login_customer()
        response = self.client.get(reverse("customer_transfer"))
        self.assertContains(response, 'name="category"')
        self.assertContains(response, "Entertainment")


class RelabelTests(TransactionTestBase):
    def make_txn(self, **extra):
        data = dict(
            transaction_type="TRANSFER", from_account=self.acc_a, to_account=self.acc_b,
            amount=Decimal("100.00"), mode_of_transaction="NETBANKING",
            status="SUCCESS", performed_by=self.cust_user, remarks="test",
        )
        data.update(extra)
        return Transaction.objects.create(**data)

    def relabel(self, txn, category, **extra):
        data = {"category": category}
        data.update(extra)
        return self.client.post(reverse("relabel_transaction", args=[txn.id]), data)

    def test_owner_can_change_the_category_only(self):
        txn = self.make_txn()
        before = self.balances()
        self.login_customer()
        self.relabel(txn, "TRAVEL")
        txn.refresh_from_db()
        self.assertEqual(txn.category, "TRAVEL")
        self.assertEqual(txn.amount, Decimal("100.00"))
        self.assertEqual(txn.status, "SUCCESS")
        self.assertEqual(self.balances(), before)

    def test_change_is_audited(self):
        txn = self.make_txn()
        self.login_customer()
        self.relabel(txn, "FOOD")
        entry = AuditLog.objects.get(action=Actions.CATEGORY_CHANGED)
        self.assertEqual(entry.actor_username, "cust1")
        self.assertEqual(entry.target_type, "TRANSACTION")
        self.assertEqual(entry.target_id, txn.id)
        self.assertIn("OTHER -> FOOD", entry.details)

    def test_other_customer_gets_404_and_nothing_changes(self):
        txn = self.make_txn()
        self.login_customer("cust2")
        self.assertEqual(self.relabel(txn, "FOOD").status_code, 404)
        txn.refresh_from_db()
        self.assertEqual(txn.category, "OTHER")

    def test_loan_payment_cannot_be_relabelled(self):
        txn = self.make_txn(transaction_type="WITHDRAW", to_account=None, is_loan_related=True)
        self.login_customer()
        self.relabel(txn, "FOOD")
        txn.refresh_from_db()
        self.assertEqual(txn.category, "OTHER")

    def test_pending_and_failed_cannot_be_relabelled(self):
        for status in ("PENDING", "FAILED"):
            txn = self.make_txn(status=status)
            self.login_customer()
            self.relabel(txn, "FOOD")
            txn.refresh_from_db()
            self.assertEqual(txn.category, "OTHER")

    def test_invalid_category_is_refused(self):
        txn = self.make_txn(category="BILLS")
        self.login_customer()
        self.relabel(txn, "PIRATES")
        txn.refresh_from_db()
        self.assertEqual(txn.category, "BILLS")
        self.assertEqual(AuditLog.objects.filter(action=Actions.CATEGORY_CHANGED).count(), 0)

    def test_staff_cannot_relabel(self):
        txn = self.make_txn()
        self.login_staff()
        self.assertEqual(self.relabel(txn, "FOOD").status_code, 302)
        txn.refresh_from_db()
        self.assertEqual(txn.category, "OTHER")

    def test_anonymous_is_sent_to_login(self):
        txn = self.make_txn()
        response = self.relabel(txn, "FOOD")
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_get_is_not_allowed(self):
        txn = self.make_txn()
        self.login_customer()
        response = self.client.get(reverse("relabel_transaction", args=[txn.id]))
        self.assertEqual(response.status_code, 405)

    def test_goes_back_to_history_by_default(self):
        txn = self.make_txn()
        self.login_customer()
        response = self.relabel(txn, "FOOD")
        self.assertEqual(response.url, reverse("transaction_history", args=[self.acc_a.id]))

    def test_outside_next_address_is_ignored(self):
        txn = self.make_txn()
        self.login_customer()
        response = self.relabel(txn, "FOOD", next="https://evil.example.com/")
        self.assertEqual(response.url, reverse("transaction_history", args=[self.acc_a.id]))

    def test_local_next_address_is_used(self):
        txn = self.make_txn()
        self.login_customer()
        response = self.relabel(txn, "FOOD", next="/transactions/my/")
        self.assertEqual(response.url, "/transactions/my/")


class HistoryCategoryColumnTests(TransactionTestBase):
    def setUp(self):
        super().setUp()
        self.txn = Transaction.objects.create(
            transaction_type="TRANSFER", from_account=self.acc_a, to_account=self.acc_b,
            amount=Decimal("100.00"), mode_of_transaction="NETBANKING",
            status="SUCCESS", performed_by=self.cust_user, category="FOOD",
        )
        self.relabel_url = reverse("relabel_transaction", args=[self.txn.id])

    def test_sender_sees_a_dropdown(self):
        self.login_customer()
        response = self.client.get(reverse("transaction_history", args=[self.acc_a.id]))
        self.assertContains(response, self.relabel_url)

    def test_receiver_does_not_see_the_senders_label_or_dropdown(self):
        self.login_customer("cust2")
        response = self.client.get(reverse("transaction_history", args=[self.acc_b.id]))
        self.assertNotContains(response, self.relabel_url)
        self.assertNotContains(response, "Food")

    def test_staff_see_the_label_as_text_without_a_dropdown(self):
        self.login_staff()
        response = self.client.get(reverse("transaction_history", args=[self.acc_a.id]))
        self.assertNotContains(response, self.relabel_url)
        self.assertContains(response, "Food")