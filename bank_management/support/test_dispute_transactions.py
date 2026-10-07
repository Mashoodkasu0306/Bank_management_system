from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from transactions.models import Transaction
from transactions.tests import TransactionTestBase

from .models import SupportCase


class DisputeTransactionTests(TransactionTestBase):
    """Disputes pick a real transaction. cust1 owns acc_a, cust2 owns acc_b."""

    def setUp(self):
        super().setUp()
        # A transfer from cust1 to cust2: both customers may dispute it.
        self.own_txn = Transaction.objects.create(
            transaction_type="TRANSFER", from_account=self.acc_a, to_account=self.acc_b,
            amount=Decimal("500.00"), status="SUCCESS", mode_of_transaction="NETBANKING",
        )
        # A deposit into cust2's account only: cust1 must not be able to dispute it.
        self.other_txn = Transaction.objects.create(
            transaction_type="DEPOSIT", to_account=self.acc_b,
            amount=Decimal("300.00"), status="SUCCESS",
        )
        # An old transaction of cust1, 100 days back (outside the 90 day window).
        self.old_txn = Transaction.objects.create(
            transaction_type="WITHDRAW", from_account=self.acc_a,
            amount=Decimal("200.00"), status="SUCCESS",
        )
        Transaction.objects.filter(pk=self.old_txn.pk).update(
            timestamp=timezone.now() - timedelta(days=100)
        )

    def dispute(self, txn):
        return self.client.post(reverse("support_raise_case"), {
            "case_type": "DISPUTE", "category": "UNAUTHORISED",
            "subject": "Not mine", "description": "I did not make this payment.",
            "transaction": txn.id,
        })

    def test_dispute_on_own_transaction_is_created(self):
        self.login_customer("cust1")
        self.dispute(self.own_txn)
        case = SupportCase.objects.get()
        self.assertEqual(case.case_type, SupportCase.DISPUTE)
        self.assertEqual(case.transaction, self.own_txn)
        self.assertEqual(case.customer, self.customer)
        self.assertEqual(case.account, self.acc_a)

    def test_receiver_can_dispute_and_gets_their_own_account(self):
        self.login_customer("cust2")
        self.dispute(self.own_txn)
        case = SupportCase.objects.get()
        self.assertEqual(case.customer, self.customer2)
        self.assertEqual(case.account, self.acc_b)

    def test_cannot_dispute_someone_elses_transaction(self):
        self.login_customer("cust1")
        response = self.dispute(self.other_txn)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(SupportCase.objects.count(), 0)

    def test_transaction_older_than_90_days_is_not_allowed(self):
        self.login_customer("cust1")
        response = self.dispute(self.old_txn)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(SupportCase.objects.count(), 0)

    def test_second_open_dispute_on_same_transaction_is_refused(self):
        self.login_customer("cust1")
        self.dispute(self.own_txn)
        self.dispute(self.own_txn)
        self.assertEqual(SupportCase.objects.count(), 1)

    def test_new_dispute_allowed_after_the_first_is_decided(self):
        self.login_customer("cust1")
        self.dispute(self.own_txn)
        first = SupportCase.objects.get()
        first.status = SupportCase.REJECTED
        first.save()
        self.dispute(self.own_txn)
        self.assertEqual(SupportCase.objects.count(), 2)

    def test_form_lists_only_my_recent_transactions(self):
        self.login_customer("cust1")
        response = self.client.get(reverse("support_raise_case"))
        offered = response.context["form"].fields["transaction"].queryset
        self.assertIn(self.own_txn, offered)
        self.assertNotIn(self.other_txn, offered)
        self.assertNotIn(self.old_txn, offered)

    def test_raising_a_dispute_moves_no_money(self):
        self.login_customer("cust1")
        before = Transaction.objects.count()
        self.dispute(self.own_txn)
        self.assertEqual(SupportCase.objects.count(), 1)
        self.assertEqual(Transaction.objects.count(), before)
        self.assertEqual(self.balances(), (Decimal("20000.00"), Decimal("5000.00")))

    def test_second_open_complaint_on_same_transaction_is_refused(self):
        self.login_customer("cust1")
        data = {
            "case_type": "COMPLAINT", "category": "OTHER",
            "subject": "Slow", "description": "Please check this payment.",
            "transaction": self.own_txn.id,
        }
        self.client.post(reverse("support_raise_case"), data)
        self.client.post(reverse("support_raise_case"), data)
        self.assertEqual(SupportCase.objects.count(), 1)

    def test_dispute_and_complaint_on_same_transaction_are_both_allowed(self):
        self.login_customer("cust1")
        self.dispute(self.own_txn)
        self.client.post(reverse("support_raise_case"), {
            "case_type": "COMPLAINT", "category": "OTHER",
            "subject": "Slow", "description": "Please check this payment.",
            "transaction": self.own_txn.id,
        })
        self.assertEqual(SupportCase.objects.count(), 2)