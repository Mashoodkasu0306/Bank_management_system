import csv
import io
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Account
from audit.models import Actions, AuditLog
from bank.models import Bank, Branch
from loans.models import Loan, LoanRepayment
from transactions.models import Transaction

from . import loan_services
from .tests import make_customer, make_employee, txn


def make_loan(customer, account, status="APPROVED", repayment_type="EMI", amount="10000", **extra):
    return Loan.objects.create(
        customer=customer, account=account, loan_type="PERSONAL",
        repayment_type=repayment_type, amount=Decimal(amount),
        tenure_months=12, status=status, **extra,
    )


def make_installment(loan, number, days_from_today, principal, interest, status="PENDING"):
    return LoanRepayment.objects.create(
        loan=loan, installment_number=number,
        due_date=timezone.localdate() + timedelta(days=days_from_today),
        emi_amount=Decimal(principal) + Decimal(interest),
        principal_component=Decimal(principal), interest_component=Decimal(interest),
        closing_balance=Decimal("0"), status=status,
        paid_date=timezone.now() if status == "PAID" else None,
    )


def loan_txn(ttype, amount, remarks, frm=None, to=None, status="SUCCESS"):
    return Transaction.objects.create(
        transaction_type=ttype, from_account=frm, to_account=to, amount=Decimal(amount),
        status=status, is_loan_related=True, remarks=remarks,
    )


def make_branches():
    bank = Bank.objects.create(name="Test Bank", code="TB")
    a = Branch.objects.create(
        bank=bank, name="Alpha", branch_code="A01", address="x",
        city="c", state="s", ifsc_code="TB0000A01",
    )
    b = Branch.objects.create(
        bank=bank, name="Beta", branch_code="B01", address="x",
        city="c", state="s", ifsc_code="TB0000B01",
    )
    return a, b


class LoanReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch_a, cls.branch_b = make_branches()
        cls.admin = User.objects.create(username="admin1")
        cls.emp_a = make_employee("emp_a", cls.branch_a)

        cust1 = make_customer("cust1")
        cust2 = make_customer("cust2")
        acc_a = Account.objects.create(customer=cust1, branch=cls.branch_a, account_type="SAVINGS", balance=0)
        acc_b = Account.objects.create(customer=cust2, branch=cls.branch_b, account_type="SAVINGS", balance=0)

        # Alpha: an EMI loan with one paid and three unpaid installments
        loan1 = make_loan(cust1, acc_a, amount="10000")
        make_installment(loan1, 1, -90, 2500, 100, status="PAID")
        make_installment(loan1, 2, -45, 2500, 75)   # 45 days late
        make_installment(loan1, 3, -10, 2500, 50)   # 10 days late
        make_installment(loan1, 4, 20, 2500, 25)    # not due yet
        # Alpha: a lump-sum loan, 2300 still to pay
        make_loan(
            cust1, acc_a, repayment_type="LUMP_SUM", amount="3000",
            lump_sum_total_payable=Decimal("3300"), lump_sum_paid=Decimal("1000"),
        )
        # Alpha: a closed loan that still has an old unpaid row; it must be ignored
        closed = make_loan(cust1, acc_a, status="CLOSED", amount="8000")
        make_installment(closed, 1, -100, 8000, 0)
        # Beta
        loan2 = make_loan(cust2, acc_b, amount="5000")
        make_installment(loan2, 1, -200, 5000, 100)  # 200 days late
        make_loan(cust2, acc_b, status="PENDING", amount="1000")

        # Money moved today
        loan_txn("DEPOSIT", "10000", "Loan disbursement - Personal Loan (Loan #1)", to=acc_a)
        loan_txn("DEPOSIT", "5000", "Loan disbursement - Personal Loan (Loan #2)", to=acc_b)
        loan_txn("DEPOSIT", "999", "Loan disbursement - waiting", to=acc_a, status="PENDING")
        loan_txn("WITHDRAW", "2600", "EMI payment - Loan #1, Installment 1", frm=acc_a)
        loan_txn("WITHDRAW", "4000", "Loan foreclosure - Loan #9 (principal 3900 + interest 100)", frm=acc_a)
        loan_txn("WITHDRAW", "800", "Lump sum payment - Loan #3", frm=acc_b)
        loan_txn("WITHDRAW", "50", "EMI payment - Loan #2", frm=acc_b, status="FAILED")
        txn("DEPOSIT", "123", to=acc_a)  # an ordinary deposit, not a loan

    def url(self):
        return reverse("reports_home")

    def admin_ctx(self, **params):
        self.client.force_login(self.admin)
        return self.client.get(self.url(), params).context

    def _rows(self, response):
        return list(csv.reader(io.StringIO(response.content.decode("utf-8"))))

    # ---- status counts ----
    def test_status_counts_for_admin(self):
        ctx = self.admin_ctx()
        by_code = {r["code"]: r["count"] for r in ctx["loan_status_rows"]}
        self.assertEqual(by_code["APPROVED"], 3)
        self.assertEqual(by_code["CLOSED"], 1)
        self.assertEqual(by_code["PENDING"], 1)
        self.assertEqual(by_code["REJECTED"], 0)
        self.assertEqual(ctx["loan_total"], 5)

    def test_status_counts_for_one_branch(self):
        ctx = self.admin_ctx(branch=self.branch_b.id)
        by_code = {r["code"]: r["count"] for r in ctx["loan_status_rows"]}
        self.assertEqual(by_code["APPROVED"], 1)
        self.assertEqual(by_code["PENDING"], 1)
        self.assertEqual(ctx["loan_total"], 2)

    # ---- outstanding ----
    def test_outstanding_for_admin(self):
        o = self.admin_ctx()["loan_outstanding"]
        self.assertEqual(o["emi_loans"], 2)
        self.assertEqual(o["outstanding_principal"], Decimal("12500"))  # 7500 + 5000
        self.assertEqual(o["scheduled_interest"], Decimal("250"))       # 75+50+25 and 100
        self.assertEqual(o["lump_loans"], 1)
        self.assertEqual(o["lump_remaining"], Decimal("2300"))

    def test_outstanding_for_one_branch(self):
        o = self.admin_ctx(branch=self.branch_b.id)["loan_outstanding"]
        self.assertEqual(o["outstanding_principal"], Decimal("5000"))
        self.assertEqual(o["scheduled_interest"], Decimal("100"))
        self.assertEqual(o["lump_remaining"], Decimal("0"))

    # ---- money in the period ----
    def test_loan_money_for_admin(self):
        m = self.admin_ctx()["loan_money"]
        self.assertEqual((m["payouts"]["count"], m["payouts"]["total"]), (2, Decimal("15000")))
        self.assertEqual((m["emi"]["count"], m["emi"]["total"]), (1, Decimal("2600")))
        self.assertEqual((m["foreclosure"]["count"], m["foreclosure"]["total"]), (1, Decimal("4000")))
        self.assertEqual((m["other"]["count"], m["other"]["total"]), (1, Decimal("800")))
        self.assertEqual((m["repayments"]["count"], m["repayments"]["total"]), (3, Decimal("7400")))

    def test_loan_money_for_one_branch(self):
        m = self.admin_ctx(branch=self.branch_a.id)["loan_money"]
        self.assertEqual(m["payouts"]["total"], Decimal("10000"))
        self.assertEqual(m["other"]["count"], 0)
        self.assertEqual(m["repayments"]["total"], Decimal("6600"))

    # ---- overdue ----
    def test_overdue_buckets_for_admin(self):
        ctx = self.admin_ctx()
        by_label = {r["label"]: r for r in ctx["overdue_rows"]}
        self.assertEqual(by_label["1-30 days"]["installments"], 1)
        self.assertEqual(by_label["1-30 days"]["amount"], Decimal("2550"))
        self.assertEqual(by_label["31-60 days"]["amount"], Decimal("2575"))
        self.assertEqual(by_label["61-90 days"]["installments"], 0)
        self.assertEqual(by_label["91-180 days"]["installments"], 0)
        self.assertEqual(by_label["Over 180 days"]["amount"], Decimal("5100"))
        total = ctx["overdue_total"]
        self.assertEqual(total["installments"], 3)  # the closed loan's row is left out
        self.assertEqual(total["loans"], 2)
        self.assertEqual(total["amount"], Decimal("10225"))

    def test_employee_sees_only_own_branch_loans(self):
        self.client.force_login(self.emp_a)
        ctx = self.client.get(self.url(), {"branch": self.branch_b.id}).context
        self.assertEqual(ctx["overdue_total"]["installments"], 2)
        self.assertEqual(ctx["overdue_total"]["amount"], Decimal("5125"))
        self.assertEqual(ctx["loan_outstanding"]["outstanding_principal"], Decimal("7500"))

    def test_branch_summary_has_loan_columns_that_add_up(self):
        ctx = self.admin_ctx()
        by_name = {r["branch"].name: r for r in ctx["branch_rows"]}
        self.assertEqual(by_name["Alpha"]["active_loans"], 2)
        self.assertEqual(by_name["Alpha"]["overdue_amount"], Decimal("5125"))
        self.assertEqual(by_name["Beta"]["active_loans"], 1)
        self.assertEqual(by_name["Beta"]["overdue_amount"], Decimal("5100"))
        self.assertEqual(
            sum(r["overdue_amount"] for r in ctx["branch_rows"]), ctx["overdue_total"]["amount"]
        )

    # ---- CSV and audit ----
    def test_loan_summary_csv(self):
        self.client.force_login(self.admin)
        rows = self._rows(self.client.get(self.url(), {"export": "loans"}))
        by_measure = {r[0]: r for r in rows}
        self.assertEqual(Decimal(by_measure["Outstanding principal (EMI loans)"][2]), Decimal("12500"))
        self.assertEqual(Decimal(by_measure["Repayments - total"][2]), Decimal("7400"))
        self.assertEqual(AuditLog.objects.filter(action=Actions.REPORT_EXPORTED).count(), 1)

    def test_overdue_summary_csv(self):
        self.client.force_login(self.admin)
        rows = self._rows(self.client.get(self.url(), {"export": "overdue"}))
        self.assertEqual(len(rows), 7)  # header, 5 age rows, total
        self.assertEqual(rows[0][0], "Age of overdue installments")
        self.assertEqual(rows[-1][0], "Total")
        self.assertEqual(Decimal(rows[-1][3]), Decimal("10225"))

    def test_overdue_detail_csv_is_scoped_for_employee(self):
        self.client.force_login(self.emp_a)
        rows = self._rows(self.client.get(self.url(), {"export": "overdue_detail", "branch": self.branch_b.id}))
        self.assertEqual(len(rows), 3)  # header + two Alpha installments
        self.assertEqual({int(r[5]) for r in rows[1:]}, {10, 45})
        entry = AuditLog.objects.get(action=Actions.REPORT_EXPORTED)
        self.assertIn("Alpha", entry.details)


class BucketEdgeTests(TestCase):
    def test_boundaries_between_age_buckets(self):
        branch, _ = make_branches()
        cust = make_customer("edge_cust")
        acc = Account.objects.create(customer=cust, branch=branch, account_type="SAVINGS", balance=0)
        loan = make_loan(cust, acc)
        for number, age in enumerate([1, 30, 31, 90, 91, 180, 181], start=1):
            make_installment(loan, number, -age, 100, 0)
        make_installment(loan, 8, 0, 100, 0)                  # due today: not late
        make_installment(loan, 9, 5, 100, 0)                  # in the future
        make_installment(loan, 10, -400, 100, 0, status="PAID")  # paid long ago

        rows, total = loan_services.overdue_by_bucket(None)
        self.assertEqual([r["installments"] for r in rows], [2, 1, 1, 2, 1])
        self.assertEqual(total["installments"], 7)
        self.assertEqual(total["loans"], 1)