from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from audit.models import Actions, AuditLog
from planning.models import RecurringPayment
from planning.recurring import run_due_payments
from planning.test_recurring_pages import PageBase
from transactions.models import Transaction


class ActionBase(PageBase):
    def url(self, name, payment):
        return reverse(name, args=[payment.id])

    def act(self, name, payment, username="cust1"):
        self.login_customer(username)
        return self.client.post(self.url(name, payment))

    def reload(self, payment):
        payment.refresh_from_db()
        return payment

    def set_state(self, payment, **fields):
        RecurringPayment.objects.filter(id=payment.id).update(**fields)


class AccessTests(ActionBase):
    def test_anonymous_post_is_sent_to_login(self):
        payment = self.make_payment()
        for name in ("recurring_pause", "recurring_resume", "recurring_cancel"):
            response = self.client.post(self.url(name, payment))
            self.assertEqual(response.status_code, 302)
            self.assertIn("login", response.url)
        self.assertEqual(self.reload(payment).status, "ACTIVE")

    def test_staff_cannot_change_a_payment(self):
        payment = self.make_payment()
        self.login_staff()
        for name in ("recurring_pause", "recurring_resume", "recurring_cancel"):
            self.assertEqual(self.client.post(self.url(name, payment)).status_code, 302)
        self.assertEqual(self.reload(payment).status, "ACTIVE")

    def test_get_is_not_allowed(self):
        payment = self.make_payment()
        self.login_customer()
        for name in ("recurring_pause", "recurring_resume", "recurring_cancel"):
            self.assertEqual(self.client.get(self.url(name, payment)).status_code, 405)


class PauseTests(ActionBase):
    def test_owner_can_pause_an_active_payment(self):
        payment = self.make_payment()
        before = self.balances()
        self.assertEqual(self.act("recurring_pause", payment).status_code, 302)
        self.assertEqual(self.reload(payment).status, "PAUSED")
        self.assertEqual(self.balances(), before)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_pause_is_audited(self):
        payment = self.make_payment()
        self.act("recurring_pause", payment)
        entry = AuditLog.objects.get(action=Actions.RECURRING_PAUSED)
        self.assertEqual(entry.actor_username, "cust1")
        self.assertEqual(entry.target_type, "RECURRING_PAYMENT")
        self.assertEqual(entry.target_id, payment.id)
        self.assertIn("Rent", entry.details)

    def test_a_paused_payment_is_not_run(self):
        payment = self.make_payment()
        self.act("recurring_pause", payment)
        self.assertEqual(run_due_payments(now=timezone.now()), [])
        self.assertEqual(Transaction.objects.count(), 0)

    def test_only_an_active_payment_can_be_paused(self):
        for status in ("PAUSED", "ENDED", "CANCELLED"):
            payment = self.make_payment(name=status, status=status)
            self.act("recurring_pause", payment)
            self.assertEqual(self.reload(payment).status, status)
        self.assertEqual(AuditLog.objects.filter(action=Actions.RECURRING_PAUSED).count(), 0)

    def test_other_customer_gets_404(self):
        payment = self.make_payment()
        self.assertEqual(self.act("recurring_pause", payment, "cust2").status_code, 404)
        self.assertEqual(self.reload(payment).status, "ACTIVE")


class ResumeTests(ActionBase):
    def test_owner_can_resume_and_failures_are_reset(self):
        payment = self.make_payment()
        self.set_state(
            payment, status="PAUSED", consecutive_failures=3,
            next_run_date=self.today + timedelta(days=5),
        )
        self.assertEqual(self.act("recurring_resume", payment).status_code, 302)
        payment = self.reload(payment)
        self.assertEqual(payment.status, "ACTIVE")
        self.assertEqual(payment.consecutive_failures, 0)

    def test_a_date_that_has_already_come_is_skipped_not_paid(self):
        payment = self.make_payment()
        self.set_state(payment, status="PAUSED", next_run_date=self.today - timedelta(days=10))
        self.act("recurring_resume", payment)
        payment = self.reload(payment)
        self.assertEqual(payment.status, "ACTIVE")
        self.assertGreater(payment.next_run_date, self.today)
        self.assertLessEqual(payment.next_run_date, self.today + timedelta(days=32))
        self.assertEqual(run_due_payments(now=timezone.now()), [])
        self.assertEqual(Transaction.objects.count(), 0)

    def test_a_payment_due_today_is_moved_past_today(self):
        payment = self.make_payment()
        self.set_state(payment, status="PAUSED", next_run_date=self.today)
        self.act("recurring_resume", payment)
        self.assertGreater(self.reload(payment).next_run_date, self.today)

    def test_a_future_date_is_kept(self):
        payment = self.make_payment()
        future = self.today + timedelta(days=5)
        self.set_state(payment, status="PAUSED", next_run_date=future)
        self.act("recurring_resume", payment)
        self.assertEqual(self.reload(payment).next_run_date, future)

    def test_resuming_past_the_end_date_ends_the_payment(self):
        payment = self.make_payment()
        self.set_state(
            payment, status="PAUSED", next_run_date=self.today - timedelta(days=10),
            end_date=self.today + timedelta(days=3),
        )
        self.act("recurring_resume", payment)
        self.assertEqual(self.reload(payment).status, "ENDED")

    def test_resume_is_audited(self):
        payment = self.make_payment()
        self.set_state(payment, status="PAUSED", next_run_date=self.today + timedelta(days=5))
        self.act("recurring_resume", payment)
        entry = AuditLog.objects.get(action=Actions.RECURRING_RESUMED)
        self.assertEqual(entry.actor_username, "cust1")
        self.assertEqual(entry.target_id, payment.id)

    def test_only_a_paused_payment_can_be_resumed(self):
        for status in ("ACTIVE", "ENDED", "CANCELLED"):
            payment = self.make_payment(name=status, status=status)
            self.act("recurring_resume", payment)
            self.assertEqual(self.reload(payment).status, status)
        self.assertEqual(AuditLog.objects.filter(action=Actions.RECURRING_RESUMED).count(), 0)

    def test_other_customer_gets_404(self):
        payment = self.make_payment(status="PAUSED")
        self.assertEqual(self.act("recurring_resume", payment, "cust2").status_code, 404)
        self.assertEqual(self.reload(payment).status, "PAUSED")


class CancelTests(ActionBase):
    def test_owner_can_cancel_an_active_payment(self):
        payment = self.make_payment()
        self.assertEqual(self.act("recurring_cancel", payment).status_code, 302)
        self.assertEqual(self.reload(payment).status, "CANCELLED")

    def test_owner_can_cancel_a_paused_payment(self):
        payment = self.make_payment(status="PAUSED")
        self.act("recurring_cancel", payment)
        self.assertEqual(self.reload(payment).status, "CANCELLED")

    def test_cancel_is_audited(self):
        payment = self.make_payment()
        self.act("recurring_cancel", payment)
        entry = AuditLog.objects.get(action=Actions.RECURRING_CANCELLED)
        self.assertEqual(entry.actor_username, "cust1")
        self.assertEqual(entry.target_id, payment.id)

    def test_a_cancelled_payment_is_not_run_and_leaves_the_list(self):
        payment = self.make_payment(name="Gym")
        self.act("recurring_cancel", payment)
        self.assertEqual(run_due_payments(now=timezone.now()), [])
        self.client.get(self.list_url)  # shows the one-time "was cancelled" message
        response = self.client.get(self.list_url)
        self.assertNotContains(response, "Gym")
        self.assertContains(response, "You have no recurring payments yet.")

    def test_a_finished_payment_cannot_be_cancelled_or_resumed(self):
        for status in ("CANCELLED", "ENDED"):
            payment = self.make_payment(name=status, status=status)
            self.act("recurring_cancel", payment)
            self.act("recurring_resume", payment)
            self.assertEqual(self.reload(payment).status, status)
        self.assertEqual(AuditLog.objects.filter(action=Actions.RECURRING_CANCELLED).count(), 0)

    def test_other_customer_gets_404(self):
        payment = self.make_payment()
        self.assertEqual(self.act("recurring_cancel", payment, "cust2").status_code, 404)
        self.assertEqual(self.reload(payment).status, "ACTIVE")

    def test_cancelling_moves_no_money(self):
        payment = self.make_payment()
        before = self.balances()
        self.act("recurring_cancel", payment)
        self.assertEqual(self.balances(), before)
        self.assertEqual(Transaction.objects.count(), 0)


class ButtonTests(ActionBase):
    def test_active_row_has_pause_and_cancel_buttons(self):
        payment = self.make_payment()
        self.login_customer()
        response = self.client.get(self.list_url)
        self.assertContains(response, self.url("recurring_pause", payment))
        self.assertContains(response, self.url("recurring_cancel", payment))
        self.assertNotContains(response, self.url("recurring_resume", payment))

    def test_paused_row_has_resume_and_cancel_buttons(self):
        payment = self.make_payment(status="PAUSED")
        self.login_customer()
        response = self.client.get(self.list_url)
        self.assertContains(response, self.url("recurring_resume", payment))
        self.assertContains(response, self.url("recurring_cancel", payment))
        self.assertNotContains(response, self.url("recurring_pause", payment))

    def test_ended_row_has_no_buttons(self):
        payment = self.make_payment(status="ENDED")
        self.login_customer()
        response = self.client.get(self.list_url)
        for name in ("recurring_pause", "recurring_resume", "recurring_cancel"):
            self.assertNotContains(response, self.url(name, payment))