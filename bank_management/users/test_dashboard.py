from django.test import TestCase, Client
from django.urls import reverse

from services.tests import make_bank_branch, make_employee
from users.dashboard import dashboard_sections, DEFAULT_ORDER


def keys(department):
    return [s["key"] for s in dashboard_sections(department)]


class DashboardOrderTestCase(TestCase):
    def test_every_block_is_always_present(self):
        for dept in ["", "TRANSACTIONS", "LOANS", "KYC", "ACCOUNT_OPENING",
                     "CARDS_SERVICES", "something-old"]:
            self.assertCountEqual(keys(dept), DEFAULT_ORDER)

    def test_no_department_keeps_the_default_order(self):
        self.assertEqual(keys(""), DEFAULT_ORDER)

    def test_each_department_sees_its_own_blocks_first(self):
        self.assertEqual(keys("TRANSACTIONS")[0], "transactions")
        self.assertEqual(keys("LOANS")[0], "loans")
        self.assertEqual(keys("KYC")[0], "kyc")
        self.assertEqual(keys("CARDS_SERVICES")[0], "cards")
        self.assertEqual(keys("ACCOUNT_OPENING")[:2], ["customers", "accounts"])

    def test_only_the_departments_own_blocks_are_marked(self):
        marked = [s["key"] for s in dashboard_sections("KYC") if s["mine"]]
        self.assertEqual(marked, ["kyc"])
        self.assertEqual([s for s in dashboard_sections("") if s["mine"]], [])


class DashboardPageTestCase(TestCase):
    def setUp(self):
        self.bank, self.branch = make_bank_branch()

    def page(self, department):
        make_employee(self.branch, department=department)
        client = Client()
        client.login(username="emp1", password="testpass123")
        return client.get(reverse("employee_dashboard")).content.decode()

    def test_kyc_employee_sees_kyc_before_transactions(self):
        html = self.page("KYC")
        self.assertLess(html.index("Pending KYC Documents"), html.index(">Deposit<"))

    def test_transactions_employee_sees_transactions_before_kyc(self):
        html = self.page("TRANSACTIONS")
        self.assertLess(html.index(">Deposit<"), html.index("Pending KYC Documents"))

    def test_nothing_is_hidden(self):
        html = self.page("KYC")
        for text in (">Deposit<", "Pending Loan Applications", "Pending ATM Card Requests"):
            self.assertIn(text, html)

    def test_department_name_is_shown(self):
        self.assertIn("Department: <strong>KYC</strong>", self.page("KYC"))

    def test_employee_without_department_sees_a_note(self):
        self.assertIn("No department assigned yet", self.page(""))
