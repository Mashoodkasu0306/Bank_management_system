from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import Account
from audit.alerts import check_failed_logins, check_large_transfer
from audit.helpers import log_action
from audit.models import AuditLog, Actions, SecurityAlert
from notifications.models import Notification
from services.tests import (
    make_bank_branch, make_customer, make_employee, make_verified_kyc,
)
from transactions.models import Transaction


# ============================================================================
# MANY FAILED LOGINS
# ============================================================================

class FailedLoginAlertTestCase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="boss", password="testpass123", email="boss@test.com"
        )
        make_customer(username="alina")
        self.client = Client()

    def attempt(self, name):
        """One failed login: write it to the log, then run the check."""
        log_action(Actions.LOGIN_FAILED, username=name)
        return check_failed_logins(name)

    def test_four_failed_logins_raise_no_alert(self):
        for _ in range(4):
            self.assertIsNone(self.attempt("alina"))
        self.assertEqual(SecurityAlert.objects.count(), 0)

    def test_fifth_failed_login_raises_an_alert_and_tells_the_admin(self):
        for _ in range(5):
            self.client.post(reverse("login"), {"username": "alina", "password": "wrong-pass"})
        alert = SecurityAlert.objects.get()
        self.assertEqual(alert.alert_type, SecurityAlert.FAILED_LOGINS)
        self.assertEqual(alert.subject, "alina")
        self.assertIn("5", alert.message)
        self.assertEqual(
            Notification.objects.filter(
                recipient=self.admin, title__startswith="Security alert"
            ).count(), 1
        )

    def test_more_failures_in_the_same_window_do_not_repeat_the_alert(self):
        for _ in range(5):
            self.attempt("alina")
        for _ in range(3):
            self.attempt("alina")
        self.assertEqual(SecurityAlert.objects.count(), 1)

    def test_failures_older_than_the_window_do_not_count(self):
        for _ in range(5):
            log_action(Actions.LOGIN_FAILED, username="alina")
        AuditLog.objects.filter(action=Actions.LOGIN_FAILED).update(
            created_at=timezone.now() - timedelta(minutes=20)
        )
        self.assertIsNone(self.attempt("alina"))
        self.assertEqual(SecurityAlert.objects.count(), 0)

    def test_two_usernames_are_counted_separately(self):
        for _ in range(3):
            self.attempt("alina")
            self.attempt("bob")
        self.assertEqual(SecurityAlert.objects.count(), 0)

    def test_a_blank_username_is_ignored(self):
        self.assertIsNone(check_failed_logins(""))
        self.assertIsNone(check_failed_logins("   "))


# ============================================================================
# UNUSUALLY LARGE TRANSFER
# ============================================================================

class LargeTransferAlertTestCase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="boss", password="testpass123", email="boss@test.com"
        )
        self.bank, self.branch = make_bank_branch()
        self.user, self.customer = make_customer(username="alina")
        bob_user, bob = make_customer(username="bob")
        self.account_a = Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="SAVINGS",
            status="ACTIVE", balance=Decimal("50000.00"),
        )
        self.account_b = Account.objects.create(
            customer=bob, branch=self.branch, account_type="SAVINGS",
            status="ACTIVE", balance=Decimal("5000.00"),
        )
        self.client = Client()

    def send(self, amount):
        return Transaction.objects.create(
            transaction_type="TRANSFER", from_account=self.account_a,
            to_account=self.account_b, amount=Decimal(amount), status="SUCCESS",
        )

    def history(self, how_many, amount="1000.00"):
        return [self.send(amount) for _ in range(how_many)]

    def test_a_big_jump_raises_an_alert(self):
        self.history(3)
        last = self.send("10000.00")
        alert = check_large_transfer(self.account_a, Decimal("10000.00"))
        self.assertIsNotNone(alert)
        self.assertEqual(alert.alert_type, SecurityAlert.LARGE_TRANSFER)
        self.assertEqual(alert.subject, self.account_a.account_no)
        self.assertEqual(alert.target_id, last.id)
        self.assertIn("alina", alert.message)
        self.assertEqual(
            Notification.objects.filter(recipient=self.admin, title__startswith="Security alert").count(), 1
        )

    def test_a_normal_amount_does_not(self):
        self.history(3)
        self.send("3000.00")
        self.assertIsNone(check_large_transfer(self.account_a, Decimal("3000.00")))

    def test_exactly_five_times_the_average_does_not(self):
        self.history(3)
        self.send("5000.00")
        self.assertIsNone(check_large_transfer(self.account_a, Decimal("5000.00")))

    def test_too_little_history_gives_no_alert(self):
        self.history(2)
        self.send("100000.00")
        self.assertIsNone(check_large_transfer(self.account_a, Decimal("100000.00")))

    def test_old_transfers_do_not_count_as_history(self):
        old = self.history(3)
        Transaction.objects.filter(id__in=[t.id for t in old]).update(
            timestamp=timezone.now() - timedelta(days=100)
        )
        self.send("100000.00")
        self.assertIsNone(check_large_transfer(self.account_a, Decimal("100000.00")))

    def test_the_fixed_limit_raises_an_alert_when_switched_on(self):
        self.send("60000.00")
        with patch("audit.alerts.LARGE_TRANSFER_FIXED_LIMIT", Decimal("50000.00")):
            alert = check_large_transfer(self.account_a, Decimal("60000.00"))
        self.assertIsNotNone(alert)
        self.assertIn("fixed limit", alert.message)

    def test_the_real_transfer_page_raises_the_alert(self):
        make_verified_kyc(self.customer)
        self.history(3, amount="100.00")
        self.client.login(username="alina", password="testpass123")
        self.client.post(reverse("customer_transfer"), {
            "from_account_no": self.account_a.account_no,
            "to_account_no": self.account_b.account_no,
            "amount": "1000.00",
        })
        self.account_a.refresh_from_db()
        self.assertEqual(self.account_a.balance, Decimal("49000.00"))
        self.assertEqual(
            SecurityAlert.objects.filter(alert_type=SecurityAlert.LARGE_TRANSFER).count(), 1
        )


# ============================================================================
# THE ALERTS PAGE
# ============================================================================

class AlertPageTestCase(TestCase):
    def setUp(self):
        self.bank, self.branch = make_bank_branch()
        self.admin = User.objects.create_superuser(
            username="boss", password="testpass123", email="boss@test.com"
        )
        self.emp_user, self.employee = make_employee(self.branch)
        self.cust_user, self.customer = make_customer(username="alina")

        self.open_alert = SecurityAlert.objects.create(
            alert_type=SecurityAlert.FAILED_LOGINS, subject="alina",
            message="5 failed login attempts for username 'alina' in the last 15 minutes.",
        )
        self.done_alert = SecurityAlert.objects.create(
            alert_type=SecurityAlert.LARGE_TRANSFER, subject="TB01-BR01-000001",
            message="Transfer looks large.", is_reviewed=True,
            reviewed_by=self.admin, reviewed_at=timezone.now(),
        )
        self.client = Client()

    def login(self, username):
        self.client.login(username=username, password="testpass123")

    def alerts_shown(self, **params):
        response = self.client.get(reverse("security_alerts"), params)
        return list(response.context["alerts"])

    def test_admin_can_open_the_page(self):
        self.login("boss")
        self.assertEqual(self.client.get(reverse("security_alerts")).status_code, 200)

    def test_employee_cannot_open_the_page(self):
        self.login("emp1")
        self.assertEqual(self.client.get(reverse("security_alerts")).status_code, 302)

    def test_customer_cannot_open_the_page(self):
        self.login("alina")
        self.assertEqual(self.client.get(reverse("security_alerts")).status_code, 302)

    def test_the_page_shows_only_open_alerts_by_default(self):
        self.login("boss")
        shown = self.alerts_shown()
        self.assertEqual(len(shown), 1)
        self.assertFalse(shown[0].is_reviewed)

    def test_the_status_filter_works(self):
        self.login("boss")
        reviewed = self.alerts_shown(status="reviewed")
        self.assertEqual([a.id for a in reviewed], [self.done_alert.id])
        self.assertEqual(len(self.alerts_shown(status="all")), 2)

    def test_reviewing_marks_the_alert_and_writes_an_audit_line(self):
        self.login("boss")
        self.client.post(reverse("review_alert", args=[self.open_alert.id]))
        self.open_alert.refresh_from_db()
        self.assertTrue(self.open_alert.is_reviewed)
        self.assertEqual(self.open_alert.reviewed_by, self.admin)
        self.assertIsNotNone(self.open_alert.reviewed_at)
        entry = AuditLog.objects.get(action=Actions.ALERT_REVIEWED)
        self.assertEqual(entry.target_id, self.open_alert.id)

    def test_reviewing_needs_a_post_request(self):
        self.login("boss")
        response = self.client.get(reverse("review_alert", args=[self.open_alert.id]))
        self.assertEqual(response.status_code, 405)
        self.open_alert.refresh_from_db()
        self.assertFalse(self.open_alert.is_reviewed)

    def test_an_employee_cannot_review(self):
        self.login("emp1")
        response = self.client.post(reverse("review_alert", args=[self.open_alert.id]))
        self.assertEqual(response.status_code, 302)
        self.open_alert.refresh_from_db()
        self.assertFalse(self.open_alert.is_reviewed)

    def test_reviewing_twice_writes_only_one_audit_line(self):
        self.login("boss")
        self.client.post(reverse("review_alert", args=[self.open_alert.id]))
        self.client.post(reverse("review_alert", args=[self.open_alert.id]))
        self.assertEqual(AuditLog.objects.filter(action=Actions.ALERT_REVIEWED).count(), 1)