from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from django.utils import timezone

from audit.models import Actions, AuditLog
from planning.models import RecurringPayment
from services.tests import make_verified_kyc
from transactions.models import Transaction
from transactions.tests import TransactionTestBase
from users.models import Employee


class StaffBase(TransactionTestBase):
    def setUp(self):
        super().setUp()
        make_verified_kyc(self.customer)
        self.today = timezone.localdate()
        self.page = reverse("run_recurring_page")

    def pay(self, **extra):
        data = dict(
            customer=self.customer, from_account=self.acc_a, to_account=self.acc_b,
            name="Rent", amount=Decimal("1000.00"), frequency="MONTHLY", category="RENT",
        )
        data.update(extra)
        payment = RecurringPayment(**data)
        payment.set_start(self.today)
        payment.save()
        return payment

    def use_department(self, department):
        Employee.objects.filter(id=self.employee.id).update(department=department)


class CommandTests(StaffBase):
    def run_command(self, *args):
        out = StringIO()
        call_command("run_recurring", *args, stdout=out)
        return out.getvalue()

    def test_pays_a_due_payment(self):
        self.pay()
        output = self.run_command()
        self.assertIn("[PAID]", output)
        self.assertIn("Done: 1 PAID.", output)
        self.assertEqual(self.balances(), (Decimal("19000.00"), Decimal("6000.00")))

    def test_dry_run_changes_nothing(self):
        payment = self.pay()
        output = self.run_command("--dry-run")
        self.assertIn("DRY RUN", output)
        self.assertIn("[PAID]", output)
        self.assertEqual(self.balances(), (Decimal("20000.00"), Decimal("5000.00")))
        self.assertEqual(Transaction.objects.count(), 0)
        payment.refresh_from_db()
        self.assertEqual(payment.next_run_date, self.today)

    def test_says_when_nothing_is_due(self):
        self.assertIn("Nothing is due.", self.run_command())

    def test_running_twice_pays_once(self):
        self.pay()
        self.run_command()
        self.assertIn("Nothing is due.", self.run_command())
        self.assertEqual(Transaction.objects.count(), 1)

    def test_scheduled_run_is_audited_as_the_system(self):
        self.pay()
        self.run_command()
        entry = AuditLog.objects.get(action=Actions.RECURRING_PAID)
        self.assertIsNone(entry.actor)
        self.assertEqual(entry.actor_username, "recurring-payments")

    def test_unexpected_error_fails_the_command(self):
        self.pay()
        out = StringIO()
        with self.assertLogs("planning.recurring", level="ERROR"):
            with mock.patch("planning.recurring._decide", side_effect=RuntimeError("boom")):
                with self.assertRaises(CommandError):
                    call_command("run_recurring", stdout=out)
        self.assertIn("[ERROR]", out.getvalue())


class StaffPageTests(StaffBase):
    def test_anonymous_is_sent_to_login(self):
        response = self.client.get(self.page)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_customer_cannot_open_it(self):
        self.login_customer()
        self.assertEqual(self.client.get(self.page).status_code, 302)

    def test_other_department_cannot_open_it(self):
        self.use_department("LOANS")
        self.login_staff()
        self.assertEqual(self.client.get(self.page).status_code, 302)

    def test_transactions_employee_sees_the_preview_and_nothing_moves(self):
        self.pay()
        self.use_department("TRANSACTIONS")
        self.login_staff()
        response = self.client.get(self.page)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rent")
        self.assertContains(response, "Would pay")
        self.assertContains(response, "Run due payments now")
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertEqual(self.balances(), (Decimal("20000.00"), Decimal("5000.00")))

    def test_page_says_when_nothing_is_due(self):
        self.use_department("TRANSACTIONS")
        self.login_staff()
        response = self.client.get(self.page)
        self.assertContains(response, "Nothing is due.")
        self.assertNotContains(response, "Run due payments now")

    def test_post_runs_the_payments_and_shows_results(self):
        self.pay()
        self.use_department("TRANSACTIONS")
        self.login_staff()
        response = self.client.post(self.page)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Run finished")
        self.assertContains(response, "1 PAID")
        self.assertEqual(self.balances(), (Decimal("19000.00"), Decimal("6000.00")))
        entry = AuditLog.objects.get(action=Actions.RECURRING_PAID)
        self.assertEqual(entry.actor_id, self.emp_user.id)

    def test_post_by_a_customer_moves_no_money(self):
        self.pay()
        self.login_customer()
        self.assertEqual(self.client.post(self.page).status_code, 302)
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertEqual(self.balances(), (Decimal("20000.00"), Decimal("5000.00")))

    def test_admin_can_open_it(self):
        User.objects.create_user("boss", password="testpass123")
        self.client.login(username="boss", password="testpass123")
        self.assertEqual(self.client.get(self.page).status_code, 200)

    def test_employee_dashboard_shows_the_link_to_the_transactions_department(self):
        self.use_department("TRANSACTIONS")
        self.login_staff()
        response = self.client.get(reverse("employee_dashboard"))
        self.assertContains(response, self.page)

    def test_employee_dashboard_hides_the_link_from_other_departments(self):
        self.use_department("LOANS")
        self.login_staff()
        response = self.client.get(reverse("employee_dashboard"))
        self.assertNotContains(response, self.page)