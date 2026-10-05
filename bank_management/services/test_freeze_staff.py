from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from audit.models import Actions, AuditLog
from notifications.models import Notification
from services.models import EmergencyFreeze
from services.test_card_controls import CardControlsTestBase
from services.test_freeze import FreezeTestBase
from services.tests import make_employee


class LiftFreezeViewsTestCase(CardControlsTestBase):
    def setUp(self):
        super().setUp()
        # emp1 (from the base class) is in Customer Support.
        make_employee(self.branch, username="kycguy", department="KYC")
        User.objects.create_superuser(username="boss", password="x", email="boss@test.com")
        self.client.post(reverse("emergency_freeze_start"))  # the customer presses the button
        self.freeze = EmergencyFreeze.objects.get(customer=self.customer)

    def as_user(self, username, password="testpass123"):
        client = Client()
        client.login(username=username, password=password)
        return client

    def lift(self, username="emp1", password="testpass123", note="Confirmed by phone"):
        client = self.as_user(username, password)
        return client.post(reverse("lift_freeze", args=[self.freeze.id]), {"note": note})

    def still_active(self):
        self.freeze.refresh_from_db()
        return self.freeze.lifted_at is None

    def test_support_employee_sees_the_active_freeze(self):
        html = self.as_user("emp1").get(reverse("frozen_customers")).content.decode()
        self.assertIn("cust1", html)

    def test_support_employee_can_lift_it(self):
        self.lift()
        self.assertFalse(self.still_active())
        self.assertEqual(self.freeze.lifted_by.username, "emp1")
        self.assertEqual(self.freeze.lift_note, "Confirmed by phone")
        self.assertEqual(self.state(self.card), "")
        self.assertEqual(AuditLog.objects.filter(action=Actions.EMERGENCY_FREEZE_LIFTED).count(), 1)

    def test_admin_can_lift_it(self):
        self.lift("boss", "x")
        self.assertFalse(self.still_active())

    def test_a_note_is_required(self):
        self.lift(note="   ")
        self.assertTrue(self.still_active())

    def test_other_departments_cannot_see_or_lift(self):
        client = self.as_user("kycguy")
        self.assertEqual(client.get(reverse("frozen_customers")).status_code, 302)
        self.lift("kycguy")
        self.assertTrue(self.still_active())

    def test_a_customer_cannot_see_or_lift(self):
        self.assertEqual(self.client.get(reverse("frozen_customers")).status_code, 302)
        self.client.post(reverse("lift_freeze", args=[self.freeze.id]), {"note": "let me out"})
        self.assertTrue(self.still_active())

    def test_lifting_needs_a_post_request(self):
        client = self.as_user("emp1")
        self.assertEqual(client.get(reverse("lift_freeze", args=[self.freeze.id])).status_code, 405)

    def test_lifting_clears_the_staff_alerts_and_tells_the_customer(self):
        self.lift()
        staff = Notification.objects.filter(related_type="FREEZE", related_id=self.freeze.id)
        self.assertTrue(staff.exists())
        self.assertEqual(staff.filter(is_read=False).count(), 0)
        told = Notification.objects.filter(recipient=self.user, title="Emergency freeze lifted")
        self.assertEqual(told.count(), 1)

    def test_lifting_twice_records_only_once(self):
        self.lift()
        self.lift()
        self.assertEqual(AuditLog.objects.filter(action=Actions.EMERGENCY_FREEZE_LIFTED).count(), 1)

    def test_card_the_customer_froze_stays_frozen_after_the_lift(self):
        mine = self.make_card(self.account, freeze_state="CUSTOMER")
        self.lift()
        self.assertEqual(self.state(mine), "CUSTOMER")

    def test_lifted_freeze_moves_to_history(self):
        self.lift()
        html = self.as_user("emp1").get(reverse("frozen_customers")).content.decode()
        self.assertIn("Confirmed by phone", html)
        self.assertIn("No active freezes", html)


class SupportDashboardBlockTestCase(FreezeTestBase):
    def page(self, username):
        client = Client()
        client.login(username=username, password="testpass123")
        return client.get(reverse("employee_dashboard")).content.decode()

    def test_support_employee_sees_the_freezes_link_first(self):
        html = self.page("emp1")  # emp1 is in Customer Support
        self.assertIn("Emergency Freezes", html)
        self.assertLess(html.index("Emergency Freezes"), html.index(">Deposit<"))

    def test_other_departments_do_not_see_it(self):
        make_employee(self.branch, username="kycguy", department="KYC")
        self.assertNotIn("Emergency Freezes", self.page("kycguy"))
