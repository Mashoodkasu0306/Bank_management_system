from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import Account
from transactions.models import Transaction
from transactions.views import get_today_debit_total
from services.tests import (
    make_bank_branch, make_customer, make_employee, make_verified_kyc,
)


class TransactionTestBase(TestCase):
    """Sets up: 2 customers, 1 employee, 2 accounts, and a web browser (client)."""

    def setUp(self):
        self.bank, self.branch = make_bank_branch()
        self.cust_user, self.customer = make_customer(username="cust1")
        self.cust2_user, self.customer2 = make_customer(username="cust2")
        self.emp_user, self.employee = make_employee(self.branch)

        self.acc_a = Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="SAVINGS",
            status="ACTIVE", balance=Decimal("20000.00"),
            daily_limit=Decimal("50000.00"),
        )
        self.acc_b = Account.objects.create(
            customer=self.customer2, branch=self.branch, account_type="SAVINGS",
            status="ACTIVE", balance=Decimal("5000.00"),
            daily_limit=Decimal("50000.00"),
        )
        self.client = Client()

    def login_staff(self):
        self.client.login(username="emp1", password="testpass123")

    def login_customer(self, username="cust1"):
        self.client.login(username=username, password="testpass123")

    def balances(self):
        self.acc_a.refresh_from_db()
        self.acc_b.refresh_from_db()
        return self.acc_a.balance, self.acc_b.balance


# ============================================================================
# DEPOSIT
# ============================================================================

class DepositTestCase(TransactionTestBase):
    def test_deposit_adds_money_and_records_success(self):
        self.login_staff()
        self.client.post(reverse("deposit"), {
            "account_no": self.acc_a.account_no, "amount": "1500.00",
        })
        a, _ = self.balances()
        self.assertEqual(a, Decimal("21500.00"))
        txn = Transaction.objects.get(to_account=self.acc_a)
        self.assertEqual(txn.status, "SUCCESS")
        self.assertEqual(txn.transaction_type, "DEPOSIT")
        self.assertEqual(txn.performed_by, self.emp_user)

    def test_zero_or_negative_deposit_is_rejected(self):
        self.login_staff()
        for bad_amount in ["0", "-500"]:
            self.client.post(reverse("deposit"), {
                "account_no": self.acc_a.account_no, "amount": bad_amount,
            })
        a, _ = self.balances()
        self.assertEqual(a, Decimal("20000.00"))
        self.assertEqual(Transaction.objects.count(), 0)

    def test_deposit_over_daily_limit_goes_pending(self):
        self.login_staff()
        self.client.post(reverse("deposit"), {
            "account_no": self.acc_a.account_no, "amount": "60000.00",
        })
        a, _ = self.balances()
        self.assertEqual(a, Decimal("20000.00"))
        txn = Transaction.objects.get(to_account=self.acc_a)
        self.assertEqual(txn.status, "PENDING")

    def test_customer_cannot_use_staff_deposit_page(self):
        self.login_customer()
        self.client.post(reverse("deposit"), {
            "account_no": self.acc_a.account_no, "amount": "1000.00",
        })
        a, _ = self.balances()
        self.assertEqual(a, Decimal("20000.00"))
        self.assertEqual(Transaction.objects.count(), 0)


# ============================================================================
# WITHDRAW
# ============================================================================

class WithdrawTestCase(TransactionTestBase):
    def test_withdraw_takes_money_and_records_success(self):
        self.login_staff()
        self.client.post(reverse("withdraw"), {
            "account_no": self.acc_a.account_no, "amount": "2500.00",
        })
        a, _ = self.balances()
        self.assertEqual(a, Decimal("17500.00"))
        txn = Transaction.objects.get(from_account=self.acc_a)
        self.assertEqual(txn.status, "SUCCESS")

    def test_withdraw_more_than_balance_fails(self):
        self.login_staff()
        self.client.post(reverse("withdraw"), {
            "account_no": self.acc_b.account_no, "amount": "9000.00",
        })
        _, b = self.balances()
        self.assertEqual(b, Decimal("5000.00"))
        txn = Transaction.objects.get(from_account=self.acc_b)
        self.assertEqual(txn.status, "FAILED")

    def test_withdraw_over_daily_limit_goes_pending(self):
        self.acc_a.balance = Decimal("100000.00")
        self.acc_a.save()
        self.login_staff()
        self.client.post(reverse("withdraw"), {
            "account_no": self.acc_a.account_no, "amount": "60000.00",
        })
        a, _ = self.balances()
        self.assertEqual(a, Decimal("100000.00"))
        txn = Transaction.objects.get(from_account=self.acc_a)
        self.assertEqual(txn.status, "PENDING")


# ============================================================================
# TRANSFER (done by staff)
# ============================================================================

class StaffTransferTestCase(TransactionTestBase):
    def post_transfer(self, from_no, to_no, amount):
        return self.client.post(reverse("transfer"), {
            "from_account_no": from_no, "to_account_no": to_no, "amount": amount,
        })

    def test_transfer_moves_money_between_accounts(self):
        self.login_staff()
        self.post_transfer(self.acc_a.account_no, self.acc_b.account_no, "3000.00")
        a, b = self.balances()
        self.assertEqual(a, Decimal("17000.00"))
        self.assertEqual(b, Decimal("8000.00"))
        txn = Transaction.objects.get()
        self.assertEqual(txn.status, "SUCCESS")
        self.assertEqual(txn.transaction_type, "TRANSFER")

    def test_transfer_to_same_account_is_blocked(self):
        self.login_staff()
        self.post_transfer(self.acc_a.account_no, self.acc_a.account_no, "100.00")
        a, _ = self.balances()
        self.assertEqual(a, Decimal("20000.00"))
        self.assertEqual(Transaction.objects.count(), 0)

    def test_transfer_with_not_enough_balance_changes_nothing(self):
        self.login_staff()
        self.post_transfer(self.acc_b.account_no, self.acc_a.account_no, "9000.00")
        a, b = self.balances()
        self.assertEqual(a, Decimal("20000.00"))
        self.assertEqual(b, Decimal("5000.00"))
        self.assertEqual(Transaction.objects.get().status, "FAILED")

    def test_transfer_over_daily_limit_goes_pending_and_moves_nothing(self):
        self.acc_a.balance = Decimal("100000.00")
        self.acc_a.save()
        self.login_staff()
        self.post_transfer(self.acc_a.account_no, self.acc_b.account_no, "60000.00")
        a, b = self.balances()
        self.assertEqual(a, Decimal("100000.00"))
        self.assertEqual(b, Decimal("5000.00"))
        self.assertEqual(Transaction.objects.get().status, "PENDING")

    def test_transfer_to_closed_account_moves_nothing(self):
        self.acc_b.status = "CLOSED"
        self.acc_b.save()
        self.login_staff()
        self.post_transfer(self.acc_a.account_no, self.acc_b.account_no, "1000.00")
        a, b = self.balances()
        self.assertEqual(a, Decimal("20000.00"))
        self.assertEqual(b, Decimal("5000.00"))
        self.assertEqual(Transaction.objects.count(), 0)

    def test_transfer_with_text_instead_of_number_is_rejected(self):
        self.login_staff()
        self.post_transfer(self.acc_a.account_no, self.acc_b.account_no, "abc")
        a, b = self.balances()
        self.assertEqual(a, Decimal("20000.00"))
        self.assertEqual(b, Decimal("5000.00"))
        self.assertEqual(Transaction.objects.count(), 0)


# ============================================================================
# SELF-SERVICE TRANSFER (done by the customer, needs finished KYC)
# ============================================================================

class CustomerTransferTestCase(TransactionTestBase):
    def post_transfer(self, from_no, to_no, amount):
        return self.client.post(reverse("customer_transfer"), {
            "from_account_no": from_no, "to_account_no": to_no, "amount": amount,
        })

    def test_customer_without_finished_kyc_is_blocked(self):
        self.login_customer()
        self.post_transfer(self.acc_a.account_no, self.acc_b.account_no, "1000.00")
        a, b = self.balances()
        self.assertEqual(a, Decimal("20000.00"))
        self.assertEqual(b, Decimal("5000.00"))
        self.assertEqual(Transaction.objects.count(), 0)

    def test_customer_with_finished_kyc_can_transfer(self):
        make_verified_kyc(self.customer)
        self.login_customer()
        self.post_transfer(self.acc_a.account_no, self.acc_b.account_no, "2000.00")
        a, b = self.balances()
        self.assertEqual(a, Decimal("18000.00"))
        self.assertEqual(b, Decimal("7000.00"))
        self.assertEqual(Transaction.objects.get().status, "SUCCESS")

    def test_customer_cannot_send_from_someone_elses_account(self):
        make_verified_kyc(self.customer2)
        self.login_customer(username="cust2")
        # cust2 tries to take money out of cust1's account
        self.post_transfer(self.acc_a.account_no, self.acc_b.account_no, "1000.00")
        a, b = self.balances()
        self.assertEqual(a, Decimal("20000.00"))
        self.assertEqual(b, Decimal("5000.00"))
        self.assertEqual(Transaction.objects.count(), 0)

    def test_customer_transfer_to_same_account_is_logged_as_failed(self):
        make_verified_kyc(self.customer)
        self.login_customer()
        self.post_transfer(self.acc_a.account_no, self.acc_a.account_no, "500.00")
        a, _ = self.balances()
        self.assertEqual(a, Decimal("20000.00"))
        self.assertEqual(Transaction.objects.get().status, "FAILED")


# ============================================================================
# APPROVING OR REJECTING PENDING TRANSACTIONS
# ============================================================================

class ApprovalTestCase(TransactionTestBase):
    def make_pending(self, txn_type, amount, from_account=None, to_account=None):
        return Transaction.objects.create(
            transaction_type=txn_type, from_account=from_account,
            to_account=to_account, amount=Decimal(amount),
            status="PENDING", performed_by=self.emp_user,
            remarks="Exceeds daily limit; awaiting approval",
        )

    def act(self, txn, action):
        return self.client.post(
            reverse("approve_transaction", args=[txn.id]), {"action": action}
        )

    def test_approving_a_deposit_adds_the_money(self):
        txn = self.make_pending("DEPOSIT", "4000.00", to_account=self.acc_a)
        self.login_staff()
        self.act(txn, "approve")
        txn.refresh_from_db()
        a, _ = self.balances()
        self.assertEqual(txn.status, "SUCCESS")
        self.assertEqual(a, Decimal("24000.00"))

    def test_approving_a_transfer_moves_the_money(self):
        txn = self.make_pending(
            "TRANSFER", "6000.00", from_account=self.acc_a, to_account=self.acc_b
        )
        self.login_staff()
        self.act(txn, "approve")
        txn.refresh_from_db()
        a, b = self.balances()
        self.assertEqual(txn.status, "SUCCESS")
        self.assertEqual(a, Decimal("14000.00"))
        self.assertEqual(b, Decimal("11000.00"))

    def test_approving_a_withdrawal_fails_if_balance_dropped_meanwhile(self):
        txn = self.make_pending("WITHDRAW", "30000.00", from_account=self.acc_b)
        self.login_staff()
        self.act(txn, "approve")
        txn.refresh_from_db()
        _, b = self.balances()
        self.assertEqual(txn.status, "FAILED")
        self.assertEqual(b, Decimal("5000.00"))

    def test_rejecting_marks_failed_and_moves_no_money(self):
        txn = self.make_pending(
            "TRANSFER", "6000.00", from_account=self.acc_a, to_account=self.acc_b
        )
        self.login_staff()
        self.act(txn, "reject")
        txn.refresh_from_db()
        a, b = self.balances()
        self.assertEqual(txn.status, "FAILED")
        self.assertEqual(a, Decimal("20000.00"))
        self.assertEqual(b, Decimal("5000.00"))

    def test_customer_cannot_approve_transactions(self):
        txn = self.make_pending("DEPOSIT", "4000.00", to_account=self.acc_a)
        self.login_customer()
        self.act(txn, "approve")
        txn.refresh_from_db()
        a, _ = self.balances()
        self.assertEqual(txn.status, "PENDING")
        self.assertEqual(a, Decimal("20000.00"))

    def test_already_finished_transaction_cannot_be_approved_again(self):
        txn = Transaction.objects.create(
            transaction_type="DEPOSIT", to_account=self.acc_a,
            amount=Decimal("4000.00"), status="SUCCESS",
        )
        self.login_staff()
        response = self.act(txn, "approve")
        a, _ = self.balances()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(a, Decimal("20000.00"))


# ============================================================================
# WHO CAN SEE TRANSACTION HISTORY
# ============================================================================

class HistoryAccessTestCase(TransactionTestBase):
    def test_owner_can_see_own_account_history(self):
        self.login_customer()
        response = self.client.get(reverse("transaction_history", args=[self.acc_a.id]))
        self.assertEqual(response.status_code, 200)

    def test_other_customer_cannot_see_the_history(self):
        self.login_customer(username="cust2")
        response = self.client.get(reverse("transaction_history", args=[self.acc_a.id]))
        self.assertEqual(response.status_code, 302)


# ============================================================================
# THE TWO COPIES OF THE DAILY-LIMIT RULE MUST AGREE
# ============================================================================

class DailyLimitConsistencyTestCase(TransactionTestBase):
    def test_view_helper_and_model_method_give_matching_answers(self):
        Transaction.objects.create(
            transaction_type="WITHDRAW", from_account=self.acc_a,
            amount=Decimal("7000.00"), status="SUCCESS",
        )
        Transaction.objects.create(
            transaction_type="TRANSFER", from_account=self.acc_a,
            to_account=self.acc_b, amount=Decimal("3000.00"), status="SUCCESS",
        )
        spent = get_today_debit_total(self.acc_a)
        remaining = self.acc_a.get_remaining_daily_limit()
        self.assertEqual(spent, Decimal("10000.00"))
        self.assertEqual(remaining, Decimal("40000.00"))
        self.assertEqual(self.acc_a.daily_limit - spent, remaining)