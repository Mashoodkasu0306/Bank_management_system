from datetime import timedelta

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from audit.alerts import FAILED_LOGIN_LIMIT, FAILED_LOGIN_WINDOW_MINUTES
from audit.models import AuditLog, Actions
from services.tests import make_customer
from users.models import Customer


def texts(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


class LoginProtectionBase(TestCase):
    def setUp(self):
        self.user, self.customer = make_customer(username="alina")
        self.client = Client()

    def attempt(self, username="alina", password="testpass123", **extra):
        data = {"username": username, "password": password}
        data.update(extra)
        return self.client.post(reverse("login"), data)

    def fail(self, times, username="alina"):
        for _ in range(times):
            self.attempt(username=username, password="wrong-password")

    def logged_in(self):
        return "_auth_user_id" in self.client.session


class LoginLockoutTests(LoginProtectionBase):
    def test_a_few_failures_do_not_lock_the_account(self):
        self.fail(FAILED_LOGIN_LIMIT - 1)
        response = self.attempt()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.logged_in())

    def test_too_many_failures_block_even_the_correct_password(self):
        self.fail(FAILED_LOGIN_LIMIT)
        response = self.attempt()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any("Too many failed attempts" in t for t in texts(response)))
        self.assertFalse(self.logged_in())

    def test_other_usernames_are_not_affected(self):
        make_customer(username="bob")
        self.fail(FAILED_LOGIN_LIMIT, username="alina")
        response = self.attempt(username="bob")
        self.assertEqual(response.status_code, 302)

    def test_unknown_username_locks_the_same_way(self):
        self.fail(FAILED_LOGIN_LIMIT, username="ghost")
        response = self.attempt(username="ghost", password="whatever")
        self.assertTrue(any("Too many failed attempts" in t for t in texts(response)))

    def test_lockout_ignores_capital_letters(self):
        self.fail(FAILED_LOGIN_LIMIT, username="ALINA")
        response = self.attempt(username="alina")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.logged_in())

    def test_old_failures_stop_counting(self):
        self.fail(FAILED_LOGIN_LIMIT)
        AuditLog.objects.filter(
            action=Actions.LOGIN_FAILED, actor_username__iexact="alina"
        ).update(created_at=timezone.now() - timedelta(minutes=FAILED_LOGIN_WINDOW_MINUTES + 5))
        response = self.attempt()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.logged_in())

    def test_a_good_login_resets_the_count(self):
        self.fail(FAILED_LOGIN_LIMIT - 1)
        self.assertEqual(self.attempt().status_code, 302)
        self.client.get(reverse("logout"))
        self.fail(FAILED_LOGIN_LIMIT - 1)
        self.assertEqual(self.attempt().status_code, 302)
        self.assertTrue(self.logged_in())


class LoginHoneypotTests(LoginProtectionBase):
    def test_a_filled_hidden_field_is_refused(self):
        response = self.attempt(website="http://spam.example")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.logged_in())

    def test_the_hidden_field_is_on_the_login_page(self):
        html = self.client.get(reverse("login")).content.decode()
        self.assertIn('name="website"', html)


class RegisterPasswordTests(TestCase):
    def setUp(self):
        User.objects.create_user(username="boss", password="testpass123")
        self.client = Client()
        self.client.login(username="boss", password="testpass123")

    def register(self, **override):
        data = {
            "username": "newbie", "password": "Zq7!mK2#vLp9",
            "customer_type": "INDIVIDUAL", "dob": "1995-05-05",
            "gender": "MALE", "address": "1 Test Road",
        }
        data.update(override)
        return self.client.post(reverse("register_customer"), data)

    def test_a_strong_password_is_accepted(self):
        self.register()
        self.assertTrue(Customer.objects.filter(user__username="newbie").exists())

    def test_an_all_number_password_is_refused(self):
        response = self.register(password="12345678")
        self.assertFalse(Customer.objects.filter(user__username="newbie").exists())
        self.assertEqual(response.status_code, 200)

    def test_a_too_short_password_is_refused(self):
        self.register(password="Ab1!")
        self.assertFalse(Customer.objects.filter(user__username="newbie").exists())

    def test_missing_username_shows_a_message_instead_of_crashing(self):
        response = self.client.post(reverse("register_customer"), {"password": "Zq7!mK2#vLp9"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Customer.objects.count(), 0)