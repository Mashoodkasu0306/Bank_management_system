from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse

from audit.helpers import log_action
from audit.models import Actions
from services.tests import make_bank_branch, make_customer, make_employee


class AuditPageTestCase(TestCase):
    def setUp(self):
        self.bank, self.branch = make_bank_branch()
        self.cust_user, self.customer = make_customer(username="alina")
        self.emp_user, self.employee = make_employee(self.branch)
        self.admin = User.objects.create_superuser(
            username="boss", password="testpass123", email="boss@test.com"
        )
        self.client = Client()

    def login(self, username):
        self.client.login(username=username, password="testpass123")

    def test_admin_can_open_the_page(self):
        self.login("boss")
        response = self.client.get(reverse("audit_log"))
        self.assertEqual(response.status_code, 200)

    def test_employee_cannot_open_the_page(self):
        self.login("emp1")
        response = self.client.get(reverse("audit_log"))
        self.assertEqual(response.status_code, 302)

    def test_customer_cannot_open_the_page(self):
        self.login("alina")
        response = self.client.get(reverse("audit_log"))
        self.assertEqual(response.status_code, 302)

    def test_not_logged_in_is_sent_to_login(self):
        response = self.client.get(reverse("audit_log"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_filter_by_action(self):
        log_action(Actions.KYC_VERIFIED, actor=self.emp_user, details="one")
        log_action(Actions.TXN_REJECTED, actor=self.emp_user, details="two")
        self.login("boss")
        response = self.client.get(reverse("audit_log"), {"action": "KYC_VERIFIED"})
        entries = list(response.context["entries"])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].action, "KYC_VERIFIED")

    def test_filter_by_username(self):
        log_action(Actions.LOGOUT, actor=self.emp_user)
        log_action(Actions.LOGOUT, actor=self.cust_user)
        self.login("boss")
        response = self.client.get(reverse("audit_log"), {"username": "alina"})
        entries = list(response.context["entries"])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].actor_username, "alina")