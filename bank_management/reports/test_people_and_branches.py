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

from .tests import make_customer, make_employee, txn


class PeopleAndBranchTests(TestCase):
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

        cust1 = make_customer("cust1")
        cust2 = make_customer("cust2")
        make_customer("cust3")  # joined now, but has no account yet
        old_cust = make_customer("old_cust")
        User.objects.filter(id=old_cust.user_id).update(
            date_joined=timezone.now() - timedelta(days=90)
        )

        cls.acc_a = Account.objects.create(customer=cust1, branch=cls.branch_a, account_type="SAVINGS", balance=0)
        cls.acc_b = Account.objects.create(customer=cust2, branch=cls.branch_b, account_type="SAVINGS", balance=0)
        old_acc = Account.objects.create(customer=old_cust, branch=cls.branch_b, account_type="SAVINGS", balance=0)
        Account.objects.filter(id=old_acc.id).update(open_date=date.today() - timedelta(days=60))

        txn("DEPOSIT", "1000", to=cls.acc_a)
        txn("WITHDRAW", "300", frm=cls.acc_a)
        txn("TRANSFER", "200", frm=cls.acc_a, to=cls.acc_b)
        txn("DEPOSIT", "500", to=cls.acc_b)

    def url(self):
        return reverse("reports_home")

    def _rows(self, response):
        return list(csv.reader(io.StringIO(response.content.decode("utf-8"))))

    # ---- new accounts and customers ----
    def test_admin_counts(self):
        self.client.force_login(self.admin)
        ctx = self.client.get(self.url()).context
        self.assertEqual(ctx["new_accounts_count"], 2)
        self.assertEqual(ctx["new_customers_count"], 3)  # cust1, cust2, cust3; not old_cust

    def test_admin_branch_filter_counts(self):
        self.client.force_login(self.admin)
        ctx = self.client.get(self.url(), {"branch": self.branch_b.id}).context
        self.assertEqual(ctx["new_accounts_count"], 1)
        self.assertEqual(ctx["new_customers_count"], 1)  # cust2 only

    def test_employee_counts_only_own_branch(self):
        self.client.force_login(self.emp_a)
        ctx = self.client.get(self.url(), {"branch": self.branch_b.id}).context
        self.assertEqual(ctx["new_accounts_count"], 1)
        self.assertEqual(ctx["new_customers_count"], 1)  # cust1; cust3 has no account in Alpha

    def test_wider_range_includes_old_records(self):
        self.client.force_login(self.admin)
        start = timezone.localdate() - timedelta(days=100)
        ctx = self.client.get(self.url(), {"start": str(start)}).context
        self.assertEqual(ctx["new_accounts_count"], 3)
        self.assertEqual(ctx["new_customers_count"], 4)

    # ---- branch summary ----
    def test_branch_summary_rows_and_totals_agree(self):
        self.client.force_login(self.admin)
        ctx = self.client.get(self.url()).context
        by_name = {r["branch"].name: r for r in ctx["branch_rows"]}
        self.assertEqual(by_name["Alpha"]["deposit_total"], Decimal("1000"))
        self.assertEqual(by_name["Alpha"]["withdraw_total"], Decimal("300"))
        self.assertEqual(by_name["Alpha"]["transfer_total"], Decimal("200"))
        self.assertEqual(by_name["Beta"]["deposit_total"], Decimal("500"))
        self.assertEqual(by_name["Alpha"]["txn_count"], 3)

        grand = ctx["grand"]
        for key in ("deposit_total", "withdraw_total", "transfer_total"):
            self.assertEqual(sum(r[key] for r in ctx["branch_rows"]), grand[key])

    def test_branch_summary_is_hidden_from_employee(self):
        self.client.force_login(self.emp_a)
        response = self.client.get(self.url())
        self.assertEqual(response.context["branch_rows"], [])
        self.assertNotContains(response, "Branch-wise summary")

    def test_employee_cannot_export_branch_summary(self):
        self.client.force_login(self.emp_a)
        response = self.client.get(self.url(), {"export": "branches"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response["Content-Type"].startswith("text/csv"))
        self.assertEqual(AuditLog.objects.filter(action=Actions.REPORT_EXPORTED).count(), 0)

    # ---- CSV and audit ----
    def test_accounts_csv(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url(), {"export": "accounts"})
        rows = self._rows(response)
        self.assertEqual(len(rows), 3)  # header + 2 new accounts
        self.assertEqual(rows[0][0], "Account no")
        self.assertEqual(AuditLog.objects.filter(action=Actions.REPORT_EXPORTED).count(), 1)

    def test_customers_csv_is_scoped_for_employee(self):
        self.client.force_login(self.emp_a)
        rows = self._rows(self.client.get(self.url(), {"export": "customers"}))
        self.assertEqual(len(rows), 2)  # header + cust1
        self.assertEqual(rows[1][0], "cust1")

    def test_branch_csv_ignores_branch_filter_and_is_audited(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url(), {"export": "branches", "branch": self.branch_a.id})
        rows = self._rows(response)
        self.assertEqual(len(rows), 3)  # header + Alpha + Beta
        entry = AuditLog.objects.get(action=Actions.REPORT_EXPORTED)
        self.assertIn("Branch-wise summary", entry.details)
        self.assertIn("All branches", entry.details)