from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import Account
from loans.models import Loan, LoanRepayment
from services.tests import make_bank_branch, make_customer


def make_account(branch, customer, balance="50000.00"):
    return Account.objects.create(
        customer=customer, branch=branch, account_type="SAVINGS",
        status="ACTIVE", balance=Decimal(balance),
    )


def make_loan(account, customer, **overrides):
    defaults = dict(
        customer=customer, account=account, loan_type="PERSONAL",
        repayment_type="EMI", amount=Decimal("10000.00"), tenure_months=6,
        interest_rate=Decimal("12.00"), status="APPROVED",
        approved_date=timezone.localtime(),
    )
    defaults.update(overrides)
    return Loan.objects.create(**defaults)


def add_repayment(loan, number, due_date, principal="1000.00",
                  status="PENDING", paid_date=None):
    return LoanRepayment.objects.create(
        loan=loan, installment_number=number, due_date=due_date,
        emi_amount=Decimal(principal), principal_component=Decimal(principal),
        interest_component=Decimal("0.00"), closing_balance=Decimal("0.00"),
        status=status, paid_date=paid_date,
    )


def expected_interest(principal, rate, days):
    daily = rate / Decimal(100) / Decimal(365)
    return (principal * daily * days).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class LoanTestBase(TestCase):
    def setUp(self):
        self.bank, self.branch = make_bank_branch()
        self.user, self.customer = make_customer()
        self.account = make_account(self.branch, self.customer)


# ============================================================================
# OUTSTANDING PRINCIPAL
# ============================================================================

class OutstandingPrincipalTestCase(LoanTestBase):
    def test_no_repayments_means_full_amount_outstanding(self):
        loan = make_loan(self.account, self.customer)
        self.assertEqual(loan.get_outstanding_principal(), Decimal("10000.00"))

    def test_only_paid_installments_reduce_principal(self):
        loan = make_loan(self.account, self.customer)
        today = timezone.localdate()
        add_repayment(loan, 1, today, principal="2000.00", status="PAID", paid_date=timezone.now())
        add_repayment(loan, 2, today, principal="3000.00", status="PAID", paid_date=timezone.now())
        add_repayment(loan, 3, today, principal="5000.00", status="PENDING")
        self.assertEqual(loan.get_outstanding_principal(), Decimal("5000.00"))

    def test_outstanding_principal_never_negative(self):
        loan = make_loan(self.account, self.customer)
        add_repayment(loan, 1, timezone.localdate(), principal="12000.00",
                      status="PAID", paid_date=timezone.now())
        self.assertEqual(loan.get_outstanding_principal(), Decimal("0.00"))


# ============================================================================
# FORECLOSURE AMOUNT
# ============================================================================

class ForeclosureAmountTestCase(LoanTestBase):
    def test_no_interest_rate_means_zero_accrued_interest(self):
        loan = make_loan(self.account, self.customer, interest_rate=None)
        principal, interest = loan.get_foreclosure_amount()
        self.assertEqual(principal, Decimal("10000.00"))
        self.assertEqual(interest, Decimal("0.00"))

    def test_interest_accrues_from_disbursement_date(self):
        # 10,000 at 12% p.a. for 30 days = 98.63
        loan = make_loan(
            self.account, self.customer,
            approved_date=timezone.localtime() - timedelta(days=30),
        )
        principal, interest = loan.get_foreclosure_amount()
        self.assertEqual(principal, Decimal("10000.00"))
        self.assertEqual(interest, Decimal("98.63"))

    def test_interest_accrues_from_last_payment_on_reduced_principal(self):
        loan = make_loan(
            self.account, self.customer,
            approved_date=timezone.localtime() - timedelta(days=60),
        )
        add_repayment(
            loan, 1, timezone.localdate(), principal="4000.00",
            status="PAID", paid_date=timezone.now() - timedelta(days=10),
        )
        paid_date = LoanRepayment.objects.get(loan=loan).paid_date
        days = (timezone.localdate() - paid_date.date()).days

        principal, interest = loan.get_foreclosure_amount()
        self.assertEqual(principal, Decimal("6000.00"))
        self.assertEqual(interest, expected_interest(Decimal("6000.00"), Decimal("12.00"), days))

    def test_no_interest_on_disbursement_day(self):
        loan = make_loan(self.account, self.customer, approved_date=timezone.localtime())
        _, interest = loan.get_foreclosure_amount()
        self.assertEqual(interest, Decimal("0.00"))


# ============================================================================
# DEFAULT DETECTION
# ============================================================================

class DefaultDetectionTestCase(LoanTestBase):
    def test_overdue_loan_with_balance_becomes_defaulted(self):
        loan = make_loan(
            self.account, self.customer, tenure_months=6,
            approved_date=timezone.localtime() - timedelta(days=400),
        )
        loan.refresh_default_status()
        loan.refresh_from_db()
        self.assertEqual(loan.status, "DEFAULTED")

    def test_loan_within_tenure_stays_approved(self):
        loan = make_loan(
            self.account, self.customer, tenure_months=12,
            approved_date=timezone.localtime() - timedelta(days=30),
        )
        loan.refresh_default_status()
        loan.refresh_from_db()
        self.assertEqual(loan.status, "APPROVED")

    def test_non_approved_loan_is_never_defaulted(self):
        loan = make_loan(
            self.account, self.customer, status="PENDING", tenure_months=6,
            approved_date=timezone.localtime() - timedelta(days=400),
        )
        loan.refresh_default_status()
        loan.refresh_from_db()
        self.assertEqual(loan.status, "PENDING")

    def test_fully_repaid_loan_past_tenure_is_not_defaulted(self):
        loan = make_loan(
            self.account, self.customer, tenure_months=6,
            approved_date=timezone.localtime() - timedelta(days=400),
        )
        add_repayment(loan, 1, timezone.localdate(), principal="10000.00",
                      status="PAID", paid_date=timezone.now())
        loan.refresh_default_status()
        loan.refresh_from_db()
        self.assertEqual(loan.status, "APPROVED")


# ============================================================================
# DAYS PAST DUE
# ============================================================================

class RepaymentDPDTestCase(LoanTestBase):
    def setUp(self):
        super().setUp()
        self.loan = make_loan(self.account, self.customer)
        self.today = timezone.localdate()

    def test_pending_overdue_10_days(self):
        r = add_repayment(self.loan, 1, self.today - timedelta(days=10))
        self.assertEqual(r.get_dpd_days(), 10)
        self.assertEqual(r.get_dpd_bucket(), "DPD 1-30")

    def test_pending_overdue_45_days(self):
        r = add_repayment(self.loan, 1, self.today - timedelta(days=45))
        self.assertEqual(r.get_dpd_bucket(), "DPD 31-60")

    def test_pending_overdue_100_days(self):
        r = add_repayment(self.loan, 1, self.today - timedelta(days=100))
        self.assertEqual(r.get_dpd_bucket(), "DPD 90+")

    def test_paid_installment_is_never_overdue(self):
        r = add_repayment(self.loan, 1, self.today - timedelta(days=50),
                          status="PAID", paid_date=timezone.now())
        self.assertEqual(r.get_dpd_days(), 0)
        self.assertEqual(r.get_dpd_bucket(), "CURRENT")

    def test_future_due_date_is_current(self):
        r = add_repayment(self.loan, 1, self.today + timedelta(days=5))
        self.assertEqual(r.get_dpd_days(), 0)
        self.assertEqual(r.get_dpd_bucket(), "CURRENT")

    def test_due_today_is_current(self):
        r = add_repayment(self.loan, 1, self.today)
        self.assertEqual(r.get_dpd_days(), 0)


# ============================================================================
# LUMP-SUM AND EMI COMPLETION
# ============================================================================

class LumpSumTestCase(LoanTestBase):
    def make_lump_sum_loan(self, total, paid):
        return make_loan(
            self.account, self.customer, repayment_type="LUMP_SUM",
            lump_sum_total_payable=total, lump_sum_paid=paid,
        )

    def test_remaining_is_total_minus_paid(self):
        loan = self.make_lump_sum_loan(Decimal("11000.00"), Decimal("4000.00"))
        self.assertEqual(loan.get_lump_sum_remaining(), Decimal("7000.00"))
        self.assertEqual(loan.get_remaining_amount(), Decimal("7000.00"))
        self.assertFalse(loan.is_fully_paid())

    def test_overpayment_never_gives_negative_remaining(self):
        loan = self.make_lump_sum_loan(Decimal("11000.00"), Decimal("12000.00"))
        self.assertEqual(loan.get_lump_sum_remaining(), Decimal("0.00"))
        self.assertTrue(loan.is_fully_paid())

    def test_no_total_set_is_not_fully_paid(self):
        loan = self.make_lump_sum_loan(None, Decimal("0.00"))
        self.assertEqual(loan.get_lump_sum_remaining(), Decimal("0.00"))
        self.assertFalse(loan.is_fully_paid())


class EMIFullyPaidTestCase(LoanTestBase):
    def test_not_fully_paid_while_installments_pending(self):
        loan = make_loan(self.account, self.customer)
        today = timezone.localdate()
        add_repayment(loan, 1, today, status="PAID", paid_date=timezone.now())
        add_repayment(loan, 2, today + timedelta(days=30), status="PENDING")
        self.assertFalse(loan.is_fully_paid())

    def test_fully_paid_when_no_pending_installments(self):
        loan = make_loan(self.account, self.customer)
        add_repayment(loan, 1, timezone.localdate(), status="PAID", paid_date=timezone.now())
        self.assertTrue(loan.is_fully_paid())