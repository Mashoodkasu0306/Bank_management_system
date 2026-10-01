from django.test import TestCase, Client, RequestFactory
from django.urls import reverse

from audit.helpers import log_action
from audit.models import AuditLog, Actions
from services.tests import make_customer


class AuditLogModelTestCase(TestCase):
    def setUp(self):
        self.user, self.customer = make_customer(username="ali")

    def test_log_action_saves_everything(self):
        entry = log_action(
            Actions.KYC_VERIFIED, actor=self.user,
            target_type="KYC_DOCUMENT", target_id=5, details="ID proof for ali",
        )
        entry.refresh_from_db()
        self.assertEqual(entry.actor, self.user)
        self.assertEqual(entry.actor_username, "ali")
        self.assertEqual(entry.action, "KYC_VERIFIED")
        self.assertEqual(entry.target_type, "KYC_DOCUMENT")
        self.assertEqual(entry.target_id, 5)
        self.assertEqual(entry.details, "ID proof for ali")
        self.assertIsNone(entry.ip_address)

    def test_ip_address_is_taken_from_the_request(self):
        request = RequestFactory().get("/", REMOTE_ADDR="10.1.2.3")
        entry = log_action(Actions.LOGOUT, request=request, actor=self.user)
        self.assertEqual(entry.ip_address, "10.1.2.3")

    def test_long_details_are_cut_to_fit(self):
        entry = log_action(Actions.KYC_VERIFIED, actor=self.user, details="x" * 900)
        self.assertEqual(len(entry.details), 500)

    def test_entry_cannot_be_edited(self):
        entry = log_action(Actions.KYC_VERIFIED, actor=self.user, details="original")
        entry.details = "changed"
        with self.assertRaises(PermissionError):
            entry.save()
        entry.refresh_from_db()
        self.assertEqual(entry.details, "original")

    def test_entry_cannot_be_deleted(self):
        entry = log_action(Actions.KYC_VERIFIED, actor=self.user)
        with self.assertRaises(PermissionError):
            entry.delete()
        self.assertEqual(AuditLog.objects.count(), 1)


class LoginRecordingTestCase(TestCase):
    def setUp(self):
        self.user, self.customer = make_customer(username="ali")
        self.client = Client()

    def test_successful_login_is_logged(self):
        self.client.post(reverse("login"), {"username": "ali", "password": "testpass123"})
        entry = AuditLog.objects.get(action=Actions.LOGIN_SUCCESS)
        self.assertEqual(entry.actor, self.user)
        self.assertEqual(entry.actor_username, "ali")
        self.assertEqual(entry.ip_address, "127.0.0.1")

    def test_failed_login_is_logged_without_the_password(self):
        self.client.post(reverse("login"), {"username": "ali", "password": "wrongpass-123"})
        entry = AuditLog.objects.get(action=Actions.LOGIN_FAILED)
        self.assertIsNone(entry.actor)
        self.assertEqual(entry.actor_username, "ali")
        everything_saved = f"{entry.actor_username}{entry.details}{entry.target_type}"
        self.assertNotIn("wrongpass-123", everything_saved)

    def test_logout_is_logged(self):
        self.client.login(username="ali", password="testpass123")
        self.client.get(reverse("logout"))
        entry = AuditLog.objects.get(action=Actions.LOGOUT)
        self.assertEqual(entry.actor, self.user)