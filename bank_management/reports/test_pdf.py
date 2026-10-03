from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Account
from audit.models import Actions, AuditLog
from bank.models import Bank, Branch

from . import pdf
from .tests import make_customer, make_employee, txn


class PdfReportTests(TestCase):
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
        cust = make_customer("cust1")
        cls.customer_user = cust.user
        cls.acc_a = Account.objects.create(customer=cust, branch=cls.branch_a, account_type="SAVINGS", balance=0)
        txn("DEPOSIT", "1000", to=cls.acc_a)

    def url(self):
        return reverse("reports_home")

    def test_admin_downloads_pdf_and_it_is_audited(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url(), {"export": "pdf"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))
        entry = AuditLog.objects.get(action=Actions.REPORT_EXPORTED)
        self.assertEqual(entry.actor, self.admin)
        self.assertIn("Full report (PDF)", entry.details)
        self.assertIn("All branches", entry.details)

    def test_employee_pdf_is_for_own_branch(self):
        self.client.force_login(self.emp_a)
        response = self.client.get(self.url(), {"export": "pdf", "branch": self.branch_b.id})
        self.assertTrue(response.content.startswith(b"%PDF"))
        entry = AuditLog.objects.get(action=Actions.REPORT_EXPORTED)
        self.assertIn("Alpha", entry.details)

    def test_customer_cannot_download_pdf(self):
        self.client.force_login(self.customer_user)
        response = self.client.get(self.url(), {"export": "pdf"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(AuditLog.objects.filter(action=Actions.REPORT_EXPORTED).count(), 0)

    def test_empty_period_still_makes_a_pdf(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url(), {"export": "pdf", "start": "2020-01-01", "end": "2020-01-31"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_sections_for_admin_and_employee(self):
        today = timezone.localdate()
        admin_titles = [s["title"] for s in pdf.build_sections(today, today, None, "admin")]
        self.assertEqual(admin_titles, [
            "Transactions by day", "New customers and accounts", "Loans",
            "Overdue installments by age", "Branch-wise summary",
        ])
        employee_titles = [s["title"] for s in pdf.build_sections(today, today, self.branch_a, "employee")]
        self.assertNotIn("Branch-wise summary", employee_titles)
        self.assertEqual(len(employee_titles), 4)

    def test_totals_row_in_sections(self):
        today = timezone.localdate()
        rows = pdf.build_sections(today, today, None, "admin")[0]["rows"]
        self.assertEqual(rows[-1], ["Total", "1", "1,000.00", "0", "0.00", "0", "0.00"])