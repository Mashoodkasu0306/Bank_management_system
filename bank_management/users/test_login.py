from django.test import TestCase, Client
from django.urls import reverse

from services.tests import make_bank_branch, make_customer, make_employee


class LoginSwitchTestCase(TestCase):
    def setUp(self):
        self.bank, self.branch = make_bank_branch()
        self.user1, _ = make_customer(username="cust1")
        self.user2, _ = make_customer(username="cust2")
        self.emp_user, _ = make_employee(self.branch)
        self.client = Client()

    def login(self, username):
        return self.client.post(reverse("login"), {"username": username, "password": "testpass123"})

    def current_user_id(self):
        return self.client.session.get("_auth_user_id")

    def test_logged_in_user_is_sent_away_from_the_login_page(self):
        self.login("cust1")
        response = self.client.get(reverse("login"), follow=True)
        self.assertEqual(response.redirect_chain[-1][0], reverse("customer_dashboard"))
        self.assertContains(response, "already logged in as cust1")

    def test_logged_in_employee_is_sent_to_the_employee_dashboard(self):
        self.login("emp1")
        response = self.client.get(reverse("login"), follow=True)
        self.assertEqual(response.redirect_chain[-1][0], reverse("employee_dashboard"))

    def test_logging_in_as_someone_else_switches_the_user(self):
        self.login("cust1")
        self.login("cust2")
        self.assertEqual(self.current_user_id(), str(self.user2.pk))

    def test_logout_clears_the_session(self):
        self.login("cust1")
        self.client.get(reverse("logout"))
        self.assertIsNone(self.current_user_id())
        response = self.client.get(reverse("customer_dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_login_and_logout_pages_are_not_cached(self):
        for name in ("login", "logout"):
            response = self.client.get(reverse(name))
            self.assertIn("no-store", response["Cache-Control"])

    def test_login_page_after_logout_shows_nobody_in_the_top_bar(self):
        self.login("cust1")
        self.client.get(reverse("logout"))
        html = self.client.get(reverse("login")).content.decode()
        self.assertNotIn("Logged in as", html)
