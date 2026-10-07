from django.test import Client, TestCase
from django.urls import reverse

from audit.helpers import log_action
from audit.models import Actions
from services.freeze import emergency_freeze
from services.tests import make_bank_branch, make_customer, make_employee
from users.security_feed import MAX_ROWS, feed_for


class SecurityFeedTestCase(TestCase):
    def setUp(self):
        self.bank, self.branch = make_bank_branch()
        self.user, self.customer = make_customer(username="cust1")
        self.other_user, self.other = make_customer(username="cust2")
        self.staff_user, self.staff = make_employee(self.branch, department="SUPPORT")
        self.client = Client()
        self.client.post(reverse("login"), {"username": "cust1", "password": "testpass123"})  # a real sign-in, so an address is recorded

    def page(self):
        return self.client.get(reverse("my_security_activity"))

    def test_the_customers_own_actions_are_listed(self):
        log_action(Actions.CARD_FROZEN, actor=self.user, details="MY-CARD-1234")
        html = self.page().content.decode()
        self.assertIn("Signed in", html)
        self.assertIn("Card frozen", html)
        self.assertIn("MY-CARD-1234", html)

    def test_other_customers_entries_are_not_shown(self):
        log_action(Actions.CARD_FROZEN, actor=self.other_user, details="OTHERS-CARD-9999")
        self.assertNotIn("OTHERS-CARD-9999", self.page().content.decode())

    def test_actions_that_are_not_on_the_list_are_hidden(self):
        log_action(Actions.REPORT_EXPORTED, actor=self.user, details="SECRET-REPORT")
        self.assertNotIn("SECRET-REPORT", self.page().content.decode())

    def test_failed_signins_on_this_username_are_counted_and_shown(self):
        log_action(Actions.LOGIN_FAILED, username="cust1")
        log_action(Actions.LOGIN_FAILED, username="CUST1")
        log_action(Actions.LOGIN_FAILED, username="someoneelse")
        response = self.page()
        self.assertEqual(response.context["failed_week"], 2)
        self.assertContains(response, "Failed sign-in attempt on your username")

    def test_a_freeze_lifted_by_staff_hides_the_staff_details(self):
        log_action(
            Actions.EMERGENCY_FREEZE_LIFTED, actor=self.staff_user,
            target_type="CUSTOMER", target_id=self.customer.id,
            details="cust1: Confirmed by phone",
        )
        html = self.page().content.decode()
        self.assertIn("Emergency freeze lifted by the bank", html)
        self.assertNotIn("Confirmed by phone", html)
        self.assertNotIn("emp1", html)

    def test_a_freeze_lifted_for_someone_else_is_not_shown(self):
        log_action(
            Actions.EMERGENCY_FREEZE_LIFTED, actor=self.staff_user,
            target_type="CUSTOMER", target_id=self.other.id, details="cust2: ok",
        )
        self.assertNotIn("lifted by the bank", self.page().content.decode())

    def test_first_sign_in_and_previous_sign_in(self):
        self.assertIn("first recorded sign-in", self.page().content.decode())
        self.client.logout()
        self.client.post(reverse("login"), {"username": "cust1", "password": "testpass123"})
        html = self.page().content.decode()
        self.assertNotIn("first recorded sign-in", html)
        self.assertIn("127.0.0.1", html)

    def test_the_freeze_status_is_shown(self):
        self.assertNotIn("ON since", self.page().content.decode())
        emergency_freeze(self.customer)
        self.assertIn("ON since", self.page().content.decode())

    def test_newest_first_and_capped(self):
        for number in range(MAX_ROWS + 20):
            log_action(Actions.CARD_FROZEN, actor=self.user, details=f"ENTRY-{number}")
        rows = feed_for(self.customer)
        self.assertEqual(len(rows), MAX_ROWS)
        self.assertEqual(rows[0]["details"], f"ENTRY-{MAX_ROWS + 19}")

    def test_staff_and_visitors_cannot_open_the_page(self):
        staff = Client()
        staff.login(username="emp1", password="testpass123")
        self.assertEqual(staff.get(reverse("my_security_activity")).status_code, 302)
        self.assertEqual(Client().get(reverse("my_security_activity")).status_code, 302)

    def test_dashboard_links_to_the_page(self):
        html = self.client.get(reverse("customer_dashboard")).content.decode()
        self.assertIn(reverse("my_security_activity"), html)
