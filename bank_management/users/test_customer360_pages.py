from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import Account
from audit.models import Actions, AuditLog
from loans.models import Loan
from services.freeze import emergency_freeze
from services.tests import make_bank_branch, make_customer, make_employee
from support.models import SupportCase

from .security_feed import feed_for

PASSWORD = "testpass123"


class Customer360PageTests(TestCase):
    def setUp(self):
        _, self.branch = make_bank_branch()
        self.cust_user, self.customer = make_customer(username="cust_a")
        make_employee(self.branch, username="emp_kyc", department="KYC")
        make_employee(self.branch, username="emp_support", department="SUPPORT")
        User.objects.create_superuser("boss", "boss@test.com", PASSWORD)
        self.account = Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="SAVINGS",
            status="ACTIVE", balance=Decimal("1234.00"),
        )
        self.url = reverse("customer_360", args=[self.customer.id])

    def login(self, username):
        self.client.logout()
        self.client.login(username=username, password=PASSWORD)

    def views_logged(self):
        return AuditLog.objects.filter(action=Actions.CUSTOMER_VIEWED)

    # ---- who may open it ----
    def test_anonymous_user_is_sent_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_customer_cannot_open_the_page_even_their_own(self):
        self.login("cust_a")
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.views_logged().count(), 0)

    def test_any_department_employee_can_open_it(self):
        self.login("emp_kyc")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cust_a")
        self.assertContains(response, self.account.account_no)
        self.assertContains(response, "1234.00")

    def test_support_employee_and_admin_can_open_it(self):
        for name in ("emp_support", "boss"):
            self.login(name)
            self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_unknown_customer_is_404_and_not_logged(self):
        self.login("emp_kyc")
        response = self.client.get(reverse("customer_360", args=[99999]))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.views_logged().count(), 0)

    # ---- audit ----
    def test_each_opening_is_audited(self):
        self.login("emp_kyc")
        self.client.get(self.url)
        entry = self.views_logged().get()
        self.assertEqual(entry.actor_username, "emp_kyc")
        self.assertEqual(entry.target_type, "CUSTOMER")
        self.assertEqual(entry.target_id, self.customer.id)
        self.client.get(self.url)
        self.assertEqual(self.views_logged().count(), 2)

    def test_staff_views_do_not_show_on_the_customers_own_feed(self):
        self.login("emp_kyc")
        self.client.get(self.url)
        self.assertEqual(feed_for(self.customer), [])

    # ---- read only ----
    def test_page_has_no_forms(self):
        self.login("emp_kyc")
        response = self.client.get(self.url)
        self.assertNotContains(response, "<form")

    def test_post_is_not_allowed(self):
        self.login("emp_kyc")
        self.assertEqual(self.client.post(self.url, {}).status_code, 405)

    # ---- what it shows ----
    def test_active_emergency_freeze_is_shown(self):
        self.login("emp_kyc")
        self.assertNotContains(self.client.get(self.url), "Emergency freeze is ACTIVE")
        emergency_freeze(self.customer)
        self.assertContains(self.client.get(self.url), "Emergency freeze is ACTIVE")

    def test_loans_are_shown(self):
        Loan.objects.create(
            customer=self.customer, account=self.account, loan_type="PERSONAL",
            amount=Decimal("10000.00"), tenure_months=12, status="PENDING",
        )
        self.login("emp_kyc")
        self.assertContains(self.client.get(self.url), "Personal Loan")

    def test_case_numbers_link_only_for_support_and_admin(self):
        case = SupportCase.objects.create(
            customer=self.customer, case_type="COMPLAINT", subject="Slow", description="d",
        )
        link = f"/support/staff/cases/{case.id}/"
        self.login("emp_kyc")
        response = self.client.get(self.url)
        self.assertContains(response, case.reference)
        self.assertNotContains(response, link)
        for name in ("emp_support", "boss"):
            self.login(name)
            self.assertContains(self.client.get(self.url), link)

    def test_customer_list_links_to_the_page(self):
        self.login("emp_kyc")
        response = self.client.get(reverse("customer_list"))
        self.assertContains(response, self.url)
        self.assertContains(response, "View 360")