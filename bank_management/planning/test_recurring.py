from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Account
from audit.models import Actions, AuditLog
from notifications.models import Notification
from planning import recurring
from planning.models import RecurringPayment
from planning.recurring import next_run_after, run_due_payments, summarize
from services.models import EmergencyFreeze
from services.tests import make_verified_kyc
from transactions.models import Transaction
from transactions.tests import TransactionTestBase


class ScheduleTests(SimpleTestCase):
    def payment(self, frequency, start):
        payment = RecurringPayment(frequency=frequency)
        payment.set_start(start)
        return payment

    def test_monthly_moves_to_the_same_day_next_month(self):
        p = self.payment("MONTHLY", date(2026, 10, 15))
        self.assertEqual(next_run_after(p, p.next_run_date), date(2026, 11, 15))

    def test_monthly_clamps_to_a_short_month_and_comes_back(self):
        p = self.payment("MONTHLY", date(2026, 1, 31))
        february = next_run_after(p, date(2026, 1, 31))
        self.assertEqual(february, date(2026, 2, 28))
        self.assertEqual(next_run_after(p, february), date(2026, 3, 31))

    def test_monthly_handles_a_leap_year(self):
        p = self.payment("MONTHLY", date(2028, 1, 31))
        self.assertEqual(next_run_after(p, date(2028, 1, 31)), date(2028, 2, 29))

    def test_monthly_wraps_the_year(self):
        p = self.payment("MONTHLY", date(2026, 12, 15))
        self.assertEqual(next_run_after(p, date(2026, 12, 15)), date(2027, 1, 15))

    def test_weekly_adds_seven_days(self):
        p = self.payment("WEEKLY", date(2026, 10, 15))
        self.assertEqual(next_run_after(p, date(2026, 10, 15)), date(2026, 10, 22))

    def test_set_start_remembers_the_day(self):
        p = self.payment("MONTHLY", date(2026, 1, 31))
        self.assertEqual(p.anchor_day, 31)
        self.assertEqual(p.next_run_date, date(2026, 1, 31))


class ModelRuleTests(TransactionTestBase):
    def candidate(self, **extra):
        data = dict(
            customer=self.customer, from_account=self.acc_a, to_account=self.acc_b,
            name="Rent", amount=Decimal("1000.00"), frequency="MONTHLY", category="RENT",
        )
        data.update(extra)
        start = data.pop("start", timezone.localdate())
        payment = RecurringPayment(**data)
        payment.set_start(start)
        return payment

    def test_valid_payment_passes(self):
        self.candidate().full_clean()

    def test_other_customers_source_account_is_refused(self):
        with self.assertRaises(ValidationError) as caught:
            self.candidate(from_account=self.acc_b).full_clean()
        self.assertIn("from_account", caught.exception.message_dict)

    def test_loan_source_account_is_refused(self):
        loan = Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="LOAN",
            status="ACTIVE", balance=Decimal("0.00"), daily_limit=Decimal("50000.00"),
        )
        with self.assertRaises(ValidationError) as caught:
            self.candidate(from_account=loan).full_clean()
        self.assertIn("from_account", caught.exception.message_dict)

    def test_same_account_is_refused(self):
        with self.assertRaises(ValidationError) as caught:
            self.candidate(to_account=self.acc_a).full_clean()
        self.assertIn("to_account", caught.exception.message_dict)

    def test_zero_amount_is_refused(self):
        with self.assertRaises(ValidationError) as caught:
            self.candidate(amount=Decimal("0.00")).full_clean()
        self.assertIn("amount", caught.exception.message_dict)

    def test_end_date_before_start_is_refused(self):
        with self.assertRaises(ValidationError) as caught:
            self.candidate(end_date=timezone.localdate() - timedelta(days=1)).full_clean()
        self.assertIn("end_date", caught.exception.message_dict)


class RunTests(TransactionTestBase):
    def setUp(self):
        super().setUp()
        make_verified_kyc(self.customer)
        self.today = timezone.localdate()

    def pay(self, **extra):
        data = dict(
            customer=self.customer, from_account=self.acc_a, to_account=self.acc_b,
            name="Rent", amount=Decimal("1000.00"), frequency="MONTHLY", category="RENT",
        )
        data.update(extra)
        start = data.pop("start", self.today)
        payment = RecurringPayment(**data)
        payment.set_start(start)
        payment.save()
        return payment

    def run_now(self, **kwargs):
        return run_due_payments(now=timezone.now(), **kwargs)

    def test_due_payment_moves_money_and_records_it(self):
        payment = self.pay()
        results = self.run_now()
        self.assertEqual([r["outcome"] for r in results], ["PAID"])
        self.assertEqual(self.balances(), (Decimal("19000.00"), Decimal("6000.00")))
        txn = Transaction.objects.get()
        self.assertEqual((txn.transaction_type, txn.status, txn.category), ("TRANSFER", "SUCCESS", "RENT"))
        self.assertEqual(txn.amount, Decimal("1000.00"))
        self.assertEqual(txn.from_account_id, self.acc_a.id)
        self.assertEqual(txn.to_account_id, self.acc_b.id)
        self.assertEqual(txn.performed_by_id, self.cust_user.id)
        self.assertFalse(txn.is_loan_related)
        payment.refresh_from_db()
        self.assertEqual(payment.next_run_date, next_run_after(payment, self.today))
        self.assertEqual(payment.status, "ACTIVE")
        self.assertIsNotNone(payment.last_run_at)
        self.assertIn("Paid", payment.last_result)

    def test_payment_not_yet_due_is_left_alone(self):
        self.pay(start=self.today + timedelta(days=1))
        self.assertEqual(self.run_now(), [])
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertEqual(self.balances(), (Decimal("20000.00"), Decimal("5000.00")))

    def test_running_twice_pays_once(self):
        self.pay()
        self.run_now()
        self.assertEqual(self.run_now(), [])
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(self.balances()[0], Decimal("19000.00"))

    def test_paused_cancelled_and_ended_payments_are_ignored(self):
        for status in ("PAUSED", "CANCELLED", "ENDED"):
            self.pay(status=status, name=status)
        self.assertEqual(self.run_now(), [])
        self.assertEqual(Transaction.objects.count(), 0)

    def test_missed_periods_are_skipped_not_repeated(self):
        payment = self.pay(frequency="WEEKLY", start=self.today - timedelta(days=21))
        self.run_now()
        self.assertEqual(Transaction.objects.count(), 1)
        payment.refresh_from_db()
        self.assertEqual(payment.next_run_date, self.today + timedelta(days=7))
        self.assertIn("2 missed", payment.last_result)

    def test_weekly_payment_moves_a_week_ahead(self):
        payment = self.pay(frequency="WEEKLY")
        self.run_now()
        payment.refresh_from_db()
        self.assertEqual(payment.next_run_date, self.today + timedelta(days=7))

    def test_insufficient_balance_fails_and_is_recorded(self):
        Account.objects.filter(id=self.acc_a.id).update(balance=Decimal("500.00"))
        payment = self.pay()
        results = self.run_now()
        self.assertEqual(results[0]["outcome"], "FAILED")
        self.assertIn("Insufficient balance", results[0]["reason"])
        txn = Transaction.objects.get()
        self.assertEqual(txn.status, "FAILED")
        self.assertEqual(self.balances(), (Decimal("500.00"), Decimal("5000.00")))
        payment.refresh_from_db()
        self.assertEqual(payment.consecutive_failures, 1)
        self.assertGreater(payment.next_run_date, self.today)
        self.assertEqual(payment.status, "ACTIVE")

    def test_frozen_customer_fails(self):
        EmergencyFreeze.objects.create(customer=self.customer)
        self.pay()
        results = self.run_now()
        self.assertEqual(results[0]["outcome"], "FAILED")
        self.assertIn("freeze", results[0]["reason"].lower())
        self.assertEqual(self.balances(), (Decimal("20000.00"), Decimal("5000.00")))

    def test_unfinished_kyc_fails(self):
        self.pay(customer=self.customer2, from_account=self.acc_b, to_account=self.acc_a)
        results = self.run_now()
        self.assertEqual(results[0]["outcome"], "FAILED")
        self.assertIn("KYC", results[0]["reason"])
        self.assertEqual(self.balances(), (Decimal("20000.00"), Decimal("5000.00")))

    def test_closed_source_account_fails(self):
        self.pay()
        Account.objects.filter(id=self.acc_a.id).update(status="CLOSED")
        results = self.run_now()
        self.assertEqual(results[0]["outcome"], "FAILED")
        self.assertIn("Source account", results[0]["reason"])

    def test_closed_destination_account_fails(self):
        self.pay()
        Account.objects.filter(id=self.acc_b.id).update(status="CLOSED")
        results = self.run_now()
        self.assertEqual(results[0]["outcome"], "FAILED")
        self.assertIn("Destination account", results[0]["reason"])

    def test_over_daily_limit_goes_to_approval_and_approval_pays(self):
        Account.objects.filter(id=self.acc_a.id).update(daily_limit=Decimal("500.00"))
        payment = self.pay()
        results = self.run_now()
        self.assertEqual(results[0]["outcome"], "PENDING")
        txn = Transaction.objects.get()
        self.assertEqual(txn.status, "PENDING")
        self.assertEqual(txn.category, "RENT")
        self.assertEqual(self.balances(), (Decimal("20000.00"), Decimal("5000.00")))
        payment.refresh_from_db()
        self.assertGreater(payment.next_run_date, self.today)
        self.assertEqual(payment.consecutive_failures, 0)

        self.login_staff()
        self.client.post(reverse("approve_transaction", args=[txn.id]), {"action": "approve"})
        txn.refresh_from_db()
        self.assertEqual(txn.status, "SUCCESS")
        self.assertEqual(self.balances(), (Decimal("19000.00"), Decimal("6000.00")))

    def test_three_failures_in_a_row_pause_the_payment(self):
        Account.objects.filter(id=self.acc_a.id).update(balance=Decimal("10.00"))
        payment = self.pay()
        results = []
        for attempt in (1, 2, 3):
            RecurringPayment.objects.filter(id=payment.id).update(next_run_date=self.today)
            results = self.run_now()
            self.assertEqual(results[0]["outcome"], "FAILED")
            payment.refresh_from_db()
            if attempt < 3:
                self.assertEqual(payment.status, "ACTIVE")
        self.assertEqual(payment.status, "PAUSED")
        self.assertEqual(payment.consecutive_failures, 3)
        self.assertIn("Paused", results[0]["reason"])

    def test_success_resets_the_failure_count(self):
        payment = self.pay(consecutive_failures=2)
        self.run_now()
        payment.refresh_from_db()
        self.assertEqual(payment.consecutive_failures, 0)

    def test_last_payment_marks_it_ended(self):
        payment = self.pay(end_date=self.today)
        results = self.run_now()
        self.assertEqual(results[0]["outcome"], "PAID")
        payment.refresh_from_db()
        self.assertEqual(payment.status, "ENDED")

    def test_payment_past_its_end_date_is_ended_without_paying(self):
        payment = self.pay()
        RecurringPayment.objects.filter(id=payment.id).update(end_date=self.today - timedelta(days=1))
        results = self.run_now()
        self.assertEqual(results[0]["outcome"], "ENDED")
        self.assertEqual(Transaction.objects.count(), 0)
        payment.refresh_from_db()
        self.assertEqual(payment.status, "ENDED")

    def test_customer_and_receiver_are_notified(self):
        self.pay()
        self.run_now()
        self.assertTrue(
            Notification.objects.filter(recipient=self.cust_user, title="Recurring payment made").exists()
        )
        self.assertTrue(
            Notification.objects.filter(recipient=self.cust2_user, title="Money received").exists()
        )

    def test_failure_notifies_the_customer(self):
        Account.objects.filter(id=self.acc_a.id).update(balance=Decimal("10.00"))
        self.pay()
        self.run_now()
        note = Notification.objects.filter(
            recipient=self.cust_user, title="Recurring payment failed"
        ).first()
        self.assertIsNotNone(note)
        self.assertIn("Insufficient balance", note.message)

    def test_paid_run_is_audited(self):
        payment = self.pay()
        self.run_now()
        entry = AuditLog.objects.get(action=Actions.RECURRING_PAID)
        self.assertIsNone(entry.actor)
        self.assertEqual(entry.actor_username, "recurring-payments")
        self.assertEqual(entry.target_type, "RECURRING_PAYMENT")
        self.assertEqual(entry.target_id, payment.id)

    def test_failed_run_is_audited(self):
        Account.objects.filter(id=self.acc_a.id).update(balance=Decimal("10.00"))
        payment = self.pay()
        self.run_now()
        entry = AuditLog.objects.get(action=Actions.RECURRING_FAILED)
        self.assertEqual(entry.target_id, payment.id)
        self.assertIn("Insufficient balance", entry.details)

    def test_staff_who_runs_it_is_recorded(self):
        self.pay()
        self.run_now(run_by=self.emp_user)
        entry = AuditLog.objects.get(action=Actions.RECURRING_PAID)
        self.assertEqual(entry.actor_id, self.emp_user.id)
        self.assertEqual(entry.actor_username, self.emp_user.get_username())

    def test_dry_run_changes_nothing(self):
        payment = self.pay()
        results = self.run_now(dry_run=True)
        self.assertEqual([r["outcome"] for r in results], ["PAID"])
        self.assertEqual(self.balances(), (Decimal("20000.00"), Decimal("5000.00")))
        self.assertEqual(Transaction.objects.count(), 0)
        payment.refresh_from_db()
        self.assertEqual(payment.next_run_date, self.today)
        self.assertEqual(AuditLog.objects.filter(action=Actions.RECURRING_PAID).count(), 0)
        self.assertEqual(Notification.objects.filter(recipient=self.cust_user).count(), 0)

    def test_dry_run_reports_failures_without_recording_them(self):
        Account.objects.filter(id=self.acc_a.id).update(balance=Decimal("10.00"))
        payment = self.pay()
        results = self.run_now(dry_run=True)
        self.assertEqual(results[0]["outcome"], "FAILED")
        self.assertIn("Insufficient", results[0]["reason"])
        self.assertEqual(Transaction.objects.count(), 0)
        payment.refresh_from_db()
        self.assertEqual(payment.consecutive_failures, 0)

    def test_one_bad_payment_does_not_stop_the_others(self):
        first = self.pay(name="First")
        second = self.pay(name="Second", amount=Decimal("500.00"))
        original = recurring._decide

        def flaky(payment, from_acc, to_acc):
            if payment.id == first.id:
                raise RuntimeError("boom")
            return original(payment, from_acc, to_acc)

        with mock.patch("planning.recurring._decide", side_effect=flaky):
            results = self.run_now()
        outcomes = {r["id"]: r["outcome"] for r in results}
        self.assertEqual(outcomes[first.id], "ERROR")
        self.assertEqual(outcomes[second.id], "PAID")
        first.refresh_from_db()
        self.assertEqual(first.next_run_date, self.today)
        self.assertEqual(self.balances()[0], Decimal("19500.00"))

    def test_two_payments_share_the_balance_and_results_are_summarised(self):
        Account.objects.filter(id=self.acc_a.id).update(balance=Decimal("1500.00"))
        self.pay(name="First")
        self.pay(name="Second")
        results = self.run_now()
        self.assertEqual([r["outcome"] for r in results], ["PAID", "FAILED"])
        self.assertEqual(self.balances()[0], Decimal("500.00"))
        self.assertEqual(summarize(results), {"PAID": 1, "FAILED": 1})