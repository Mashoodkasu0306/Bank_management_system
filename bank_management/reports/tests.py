import csv
import io
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Account
from audit.models import Actions, AuditLog
from bank.models import Bank, Branch
from transactions.models import Transaction
from users.models import Customer, Employee

from .exports import _safe


def make_customer(username):
    user = User.objects.create(username=username)
    return Customer.objects.create(
        user=user, customer_type="INDIVIDUAL", dob=date(1990, 1, 1),
        gender="MALE", address="x", kyc_status="VERIFIED",
    )


def make_employee(username, branch):
    user = User.objects.create(username=username)
    Employee.objects.create(
        user=user, branch=branch, role="Teller", department="Ops",
        salary=Decimal("1000"), date_of_joining=date(2020, 1, 1),
    )
    return user


def txn(ttype, amount, status="SUCCESS", frm=None, to=None, loan=False):
    return Transaction.objects.create(
        transaction_type=ttype, from_account=frm, to_account=to,
        amount=Decimal(amount), status=status, is_loan_related=loan,
    )


class ReportsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        bank = Bank.objects.create(name="Test Bank", code="TB")
        cls.branch_a = Branch.objects.create(
            bank=bank, name="Alpha", branch_code="A01", address="x",
            city="c", state="s", ifsc_code="TB0000A01",
        )
        cls.branch_b = Branch.objects.create(
            bank=bank, name="Beta", branch_code="B01", address="x",
            city="c", state="s", ifsc_code="TB0000B01",
        )
        cls.admin = User.objects.create(username="admin1")
        cls.emp_a = make_employee("emp_a", cls.branch_a)
        cls.emp_none = make_employee("emp_none", None)

        cust1 = make_customer("cust1")
        cust2 = make_customer("cust2")
        cls.customer_user = cust1.user
        cls.acc_a = Account.objects.create(customer=cust1, branch=cls.branch_a, account_type="SAVINGS", balance=0)
        cls.acc_b = Account.objects.create(customer=cust2, branch=cls.branch_b, account_type="SAVINGS", balance=0)

        # Counted
        txn("DEPOSIT", "1000", to=cls.acc_a)
        txn("WITHDRAW", "300", frm=cls.acc_a)
        txn("TRANSFER", "200", frm=cls.acc_a, to=cls.acc_b)
        txn("DEPOSIT", "500", to=cls.acc_b)
        # Not counted in totals
        txn("DEPOSIT", "9000", to=cls.acc_a, loan=True)
        txn("DEPOSIT", "70", status="PENDING", to=cls.acc_a)
        old = txn("DEPOSIT", "777", to=cls.acc_a)
        Transaction.objects.filter(id=old.id).update(timestamp=timezone.now() - timedelta(days=60))
        # Failed
        txn("WITHDRAW", "50", status="FAILED", frm=cls.acc_a)
        txn("WITHDRAW", "60", status="FAILED", frm=cls.acc_b)

    def url(self):
        return reverse("reports_home")

    # ---- access ----
    def test_anonymous_is_sent_to_login(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_customer_is_turned_away(self):
        self.client.force_login(self.customer_user)
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 302)
        response = self.client.get(self.url(), {"export": "totals"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(AuditLog.objects.filter(action=Actions.REPORT_EXPORTED).count(), 0)

    def test_employee_without_branch_is_turned_away(self):
        self.client.force_login(self.emp_none)
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 302)

    # ---- totals ----
    def test_admin_sees_all_branches_and_leaves_out_loan_pending_and_old(self):
        self.client.force_login(self.admin)
        grand = self.client.get(self.url()).context["grand"]
        self.assertEqual(grand["deposit_total"], Decimal("1500"))
        self.assertEqual(grand["deposit_count"], 2)
        self.assertEqual(grand["withdraw_total"], Decimal("300"))
        self.assertEqual(grand["transfer_total"], Decimal("200"))
        self.assertEqual(grand["transfer_count"], 1)

    def test_admin_branch_filter(self):
        self.client.force_login(self.admin)
        grand = self.client.get(self.url(), {"branch": self.branch_b.id}).context["grand"]
        self.assertEqual(grand["deposit_total"], Decimal("500"))
        self.assertEqual(grand["withdraw_total"], Decimal("0"))
        self.assertEqual(grand["transfer_total"], Decimal("0"))

    def test_employee_sees_only_own_branch_and_ignores_branch_param(self):
        self.client.force_login(self.emp_a)
        response = self.client.get(self.url(), {"branch": self.branch_b.id})
        self.assertEqual(response.context["branch_label"], "Alpha")
        grand = response.context["grand"]
        self.assertEqual(grand["deposit_total"], Decimal("1000"))
        self.assertEqual(grand["transfer_total"], Decimal("200"))

    def test_old_transaction_appears_when_range_covers_it(self):
        self.client.force_login(self.admin)
        start = timezone.localdate() - timedelta(days=90)
        grand = self.client.get(self.url(), {"start": str(start)}).context["grand"]
        self.assertEqual(grand["deposit_total"], Decimal("2277"))

    def test_bad_dates_do_not_crash(self):
        self.client.force_login(self.admin)
        for params in (
            {"start": "abc", "end": "2026-13-45"},
            {"start": "2026-02-31"},
            {"start": "2026-10-10", "end": "2026-01-01"},
            {"start": "2000-01-01"},
        ):
            response = self.client.get(self.url(), params)
            self.assertEqual(response.status_code, 200, params)

    def test_range_is_limited(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url(), {"start": "2000-01-01", "end": "2026-10-01"})
        self.assertEqual((response.context["end"] - response.context["start"]).days, 366)

    # ---- CSV and audit ----
    def _rows(self, response):
        return list(csv.reader(io.StringIO(response.content.decode("utf-8"))))

    def test_totals_csv_and_audit_entry(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url(), {"export": "totals"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/csv"))
        rows = self._rows(response)
        self.assertEqual(len(rows), 3)  # header, today, total
        self.assertEqual(rows[0][0], "Date")
        self.assertEqual(Decimal(rows[-1][2]), Decimal("1500"))

        entry = AuditLog.objects.get(action=Actions.REPORT_EXPORTED)
        self.assertEqual(entry.actor, self.admin)
        self.assertIn("All branches", entry.details)

    def test_failed_csv_is_scoped_for_employee(self):
        self.client.force_login(self.emp_a)
        rows = self._rows(self.client.get(self.url(), {"export": "failed", "branch": self.branch_b.id}))
        self.assertEqual(len(rows), 2)  # header + the one failed transaction of branch A
        self.assertEqual(Decimal(rows[1][4]), Decimal("50"))

        self.client.force_login(self.admin)
        rows = self._rows(self.client.get(self.url(), {"export": "failed"}))
        self.assertEqual(len(rows), 3)

    def test_formula_text_is_defused(self):
        self.assertEqual(_safe("=1+1"), "'=1+1")
        self.assertEqual(_safe("-5"), "'-5")
        self.assertEqual(_safe("normal"), "normal")
        self.assertEqual(_safe(Decimal("-5")), Decimal("-5"))