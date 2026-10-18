from django.conf import settings
from django.test import TestCase
from django.urls import reverse


class SecuritySettingsTests(TestCase):
    def test_session_cookie_is_http_only_and_samesite(self):
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, "Lax")
        self.assertEqual(settings.CSRF_COOKIE_SAMESITE, "Lax")

    def test_idle_timeout_is_short(self):
        self.assertLessEqual(settings.SESSION_COOKIE_AGE, 3600)
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)

    def test_secret_key_is_set(self):
        self.assertTrue(settings.SECRET_KEY)

    def test_login_page_sends_security_headers(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Referrer-Policy"], "same-origin")