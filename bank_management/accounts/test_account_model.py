from decimal import Decimal
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from bank.models import Branch
from accounts.models import Account
from transactions.models import Transaction
from services.tests import make_bank_branch, make_customer


# ============================================================================
# ACCOUNT NUMBER TESTS
# ============================================================================

class AccountNumberTestCase(TestCase):
    def setUp(self):
        self.bank, self.branch = make_bank_branch()
        self.user, self.customer = make_customer()

    def make_account(self, branch=None):
        return Account.objects.create(
            customer=self.customer, branch=branch or self.branch,
            account_type="SAVINGS", status="ACTIVE", balance=Decimal("0.00"),
            daily_limit=Decimal("50000.00"),
        )

    def test_first_account_number_format(self):
        account = self.make_account()
        self.assertEqual(account.account_no, "TB01-BR01-000001")

    def test_numbers_go_up_one_by_one_in_same_branch(self):
        first = self.make_account()
        second = self.make_account()
        self.assertEqual(first.account_no, "TB01-BR01-000001")
        self.assertEqual(second.account_no, "TB01-BR01-000002")

    def test_new_branch_starts_again_from_one(self):
        self.make_account()
        branch2 = Branch.objects.create(
            bank=self.bank, name="Second Branch", branch_code="BR02",
            address="456 Test St", city="Test City", state="Test State",
            ifsc_code="TB0100002",
        )
        account = self.make_account(branch=branch2)
        self.assertEqual(account.account_no, "TB01-BR02-000001")


# ============================================================================
# DAILY LIMIT TESTS
# ============================================================================

class DailyLimitTestCase(TestCase):
    def setUp(self):
        self.bank, self.branch = make_bank_branch()
        self.user, self.customer = make_customer()
        self.account = Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="SAVINGS",
            status="ACTIVE", balance=Decimal("100000.00"),
            daily_limit=Decimal("50000.00"),
        )

    def spend(self, amount, txn_type="WITHDRAW", status="SUCCESS", loan_related=False):
        return Transaction.objects.create(
            transaction_type=txn_type, from_account=self.account,
            amount=Decimal(amount), status=status, is_loan_related=loan_related,
        )

    def test_full_limit_when_nothing_spent(self):
        self.assertEqual(self.account.get_remaining_daily_limit(), Decimal("50000.00"))

    def test_withdraw_and_transfer_both_use_up_the_limit(self):
        self.spend("10000.00", txn_type="WITHDRAW")
        self.spend("5000.00", txn_type="TRANSFER")
        self.assertEqual(self.account.get_remaining_daily_limit(), Decimal("35000.00"))

    def test_money_coming_in_does_not_use_up_the_limit(self):
        Transaction.objects.create(
            transaction_type="DEPOSIT", to_account=self.account,
            amount=Decimal("20000.00"), status="SUCCESS",
        )
        self.assertEqual(self.account.get_remaining_daily_limit(), Decimal("50000.00"))

    def test_failed_and_pending_transactions_are_ignored(self):
        self.spend("8000.00", status="FAILED")
        self.spend("9000.00", status="PENDING")
        self.assertEqual(self.account.get_remaining_daily_limit(), Decimal("50000.00"))

    def test_loan_related_transactions_are_ignored(self):
        self.spend("15000.00", loan_related=True)
        self.assertEqual(self.account.get_remaining_daily_limit(), Decimal("50000.00"))

    def test_yesterdays_spending_does_not_count_today(self):
        txn = self.spend("20000.00")
        txn.timestamp = timezone.now() - timedelta(days=1)
        txn.save()
        self.assertEqual(self.account.get_remaining_daily_limit(), Decimal("50000.00"))

    def test_remaining_never_goes_below_zero(self):
        self.spend("60000.00")
        self.assertEqual(self.account.get_remaining_daily_limit(), 0)