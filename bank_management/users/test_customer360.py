from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from accounts.models import Account
from audit.helpers import log_action
from audit.models import Actions, AuditLog
from loans.models import Loan, LoanRepayment
from services.freeze import emergency_freeze
from services.models import ATMCardRequest, ChequebookRequest, KYCVerification
from services.tests import make_bank_branch, make_customer
from support.models import SupportCase
from transactions.models import Transaction

from .customer360 import RECENT_CARDS, RECENT_TRANSACTIONS, build_customer_360


class Customer360DataTests(TestCase):
    def setUp(self):
        _, self.branch = make_bank_branch()
        self.user, self.customer = make_customer(username="cust_a")
        self.other_user, self.other = make_customer(username="cust_b")
        self.acc = self.make_account(self.customer, "SAVINGS", "ACTIVE", "1000.00")
        self.other_acc = self.make_account(self.other, "SAVINGS", "ACTIVE", "9000.00")

    def make_account(self, customer, account_type, status, balance):
        return Account.objects.create(
            customer=customer, branch=self.branch, account_type=account_type,
            status=status, balance=Decimal(balance),
        )

    def data(self):
        return build_customer_360(self.customer)

    def make_loan(self, customer, account, status, **extra):
        return Loan.objects.create(
            customer=customer, account=account, loan_type="PERSONAL",
            amount=Decimal("10000.00"), tenure_months=12, status=status, **extra
        )

    # ---- nothing there yet ----
    def test_customer_with_nothing_gets_empty_blocks(self):
        _, empty = make_customer(username="cust_empty")
        data = build_customer_360(empty)
        self.assertEqual(data["accounts"], [])
        self.assertEqual(data["total_balance"], Decimal("0.00"))
        self.assertEqual(data["recent_transactions"], [])
        self.assertEqual(data["loans"], [])
        self.assertEqual(data["cards"], [])
        self.assertEqual(data["cheque_books"], [])
        self.assertEqual(data["cases"], [])
        self.assertEqual(data["open_case_count"], 0)
        self.assertEqual(data["security_rows"], [])
        self.assertEqual(data["failed_week"], 0)
        self.assertIsNone(data["kyc"])
        self.assertIsNone(data["freeze"])

    # ---- profile ----
    def test_kyc_record_is_included_when_it_exists(self):
        self.assertIsNone(self.data()["kyc"])
        KYCVerification.objects.create(customer=self.customer, status="PENDING")
        self.assertEqual(self.data()["kyc"].status, "PENDING")

    def test_active_emergency_freeze_is_included(self):
        self.assertIsNone(self.data()["freeze"])
        freeze, _count = emergency_freeze(self.customer)
        self.assertEqual(self.data()["freeze"].id, freeze.id)

    # ---- accounts ----
    def test_only_this_customers_accounts_are_listed(self):
        ids = {a.id for a in self.data()["accounts"]}
        self.assertEqual(ids, {self.acc.id})

    def test_total_balance_counts_only_active_savings_and_current(self):
        self.make_account(self.customer, "CURRENT", "ACTIVE", "500.00")
        self.make_account(self.customer, "SAVINGS", "CLOSED", "700.00")
        self.make_account(self.customer, "LOAN", "ACTIVE", "300.00")
        data = self.data()
        self.assertEqual(len(data["accounts"]), 4)
        self.assertEqual(data["total_balance"], Decimal("1500.00"))

    # ---- transactions ----
    def test_recent_transactions_are_limited_newest_first_and_only_mine(self):
        for i in range(RECENT_TRANSACTIONS + 2):
            Transaction.objects.create(
                transaction_type="DEPOSIT", to_account=self.acc,
                amount=Decimal("10.00"), status="SUCCESS", remarks=f"t{i}",
            )
        Transaction.objects.create(
            transaction_type="DEPOSIT", to_account=self.other_acc,
            amount=Decimal("10.00"), status="SUCCESS", remarks="not mine",
        )
        rows = self.data()["recent_transactions"]
        self.assertEqual(len(rows), RECENT_TRANSACTIONS)
        self.assertEqual(rows[0].remarks, f"t{RECENT_TRANSACTIONS + 1}")
        self.assertNotIn("not mine", [t.remarks for t in rows])

    def test_sent_and_received_both_show_and_own_transfer_shows_once(self):
        acc2 = self.make_account(self.customer, "SAVINGS", "ACTIVE", "100.00")
        Transaction.objects.create(
            transaction_type="TRANSFER", from_account=self.acc, to_account=acc2,
            amount=Decimal("5.00"), status="SUCCESS", remarks="between mine",
        )
        Transaction.objects.create(
            transaction_type="TRANSFER", from_account=self.other_acc, to_account=self.acc,
            amount=Decimal("7.00"), status="SUCCESS", remarks="sent to me",
        )
        remarks = sorted(t.remarks for t in self.data()["recent_transactions"])
        self.assertEqual(remarks, ["between mine", "sent to me"])

    # ---- loans ----
    def test_approved_emi_loan_shows_remaining_next_installment_and_overdue(self):
        today = timezone.localdate()
        loan = self.make_loan(
            self.customer, self.acc, "APPROVED", repayment_type="EMI",
            interest_rate=Decimal("12.00"), emi_amount=Decimal("900.00"),
            approved_date=timezone.now(),
        )
        LoanRepayment.objects.create(
            loan=loan, installment_number=1, due_date=today - timedelta(days=60),
            emi_amount=Decimal("900.00"), principal_component=Decimal("800.00"), status="PAID",
        )
        LoanRepayment.objects.create(
            loan=loan, installment_number=2, due_date=today - timedelta(days=1),
            emi_amount=Decimal("900.00"), principal_component=Decimal("800.00"), status="PENDING",
        )
        LoanRepayment.objects.create(
            loan=loan, installment_number=3, due_date=today + timedelta(days=30),
            emi_amount=Decimal("900.00"), principal_component=Decimal("800.00"), status="PENDING",
        )
        row = self.data()["loans"][0]
        self.assertEqual(row["loan"].id, loan.id)
        self.assertGreaterEqual(row["remaining"], Decimal("9200.00"))
        self.assertEqual(row["next_installment"].installment_number, 2)
        self.assertEqual(row["overdue_count"], 1)

    def test_pending_loan_has_no_remaining_or_installment(self):
        self.make_loan(self.customer, self.acc, "PENDING")
        row = self.data()["loans"][0]
        self.assertIsNone(row["remaining"])
        self.assertIsNone(row["next_installment"])
        self.assertEqual(row["overdue_count"], 0)

    def test_other_customers_loans_are_not_shown(self):
        self.make_loan(self.other, self.other_acc, "PENDING")
        self.assertEqual(self.data()["loans"], [])

    # ---- cards, cheque books, cases ----
    def test_cards_and_cheque_books_are_limited_and_only_mine(self):
        for _ in range(RECENT_CARDS + 2):
            ATMCardRequest.objects.create(account=self.acc, delivery_address="x")
        ATMCardRequest.objects.create(account=self.other_acc, delivery_address="y")
        ChequebookRequest.objects.create(account=self.acc, leaf_count=25, delivery_address="x")
        ChequebookRequest.objects.create(account=self.other_acc, leaf_count=25, delivery_address="y")
        data = self.data()
        self.assertEqual(len(data["cards"]), RECENT_CARDS)
        self.assertTrue(all(c.account.customer_id == self.customer.id for c in data["cards"]))
        self.assertEqual(len(data["cheque_books"]), 1)

    def test_support_cases_and_open_count(self):
        SupportCase.objects.create(
            customer=self.customer, case_type="COMPLAINT", subject="Open one", description="d",
        )
        SupportCase.objects.create(
            customer=self.customer, case_type="COMPLAINT", subject="Done one", description="d",
            status=SupportCase.ACCEPTED,
        )
        SupportCase.objects.create(
            customer=self.other, case_type="COMPLAINT", subject="Not mine", description="d",
        )
        data = self.data()
        self.assertEqual(len(data["cases"]), 2)
        self.assertEqual(data["open_case_count"], 1)

    # ---- security ----
    def test_security_rows_are_only_this_customers(self):
        log_action(Actions.LOGIN_SUCCESS, actor=self.user)
        log_action(Actions.LOGIN_SUCCESS, actor=self.other_user)
        rows = self.data()["security_rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["label"], "Signed in")

    def test_failed_logins_count_only_the_last_seven_days(self):
        log_action(Actions.LOGIN_FAILED, username="cust_a")
        old = log_action(Actions.LOGIN_FAILED, username="cust_a")
        AuditLog.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=8))
        log_action(Actions.LOGIN_FAILED, username="cust_b")
        self.assertEqual(self.data()["failed_week"], 1)