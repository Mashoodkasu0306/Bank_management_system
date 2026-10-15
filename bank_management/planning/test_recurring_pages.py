from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from accounts.models import Account
from audit.models import Actions, AuditLog
from planning.models import RecurringPayment
from planning.recurring_forms import MAX_RECURRING_PAYMENTS
from services.models import EmergencyFreeze
from services.tests import make_verified_kyc
from transactions.models import Transaction
from transactions.tests import TransactionTestBase


class PageBase(TransactionTestBase):
    def setUp(self):
        super().setUp()
        make_verified_kyc(self.customer)
        self.today = timezone.localdate()
        self.list_url = reverse("my_recurring")
        self.new_url = reverse("recurring_create")

    def payload(self, **extra):
        data = {
            "from_account": self.acc_a.id,
            "to_account_no": self.acc_b.account_no,
            "name": "Rent",
            "amount": "1000.00",
            "category": "RENT",
            "frequency": "MONTHLY",
            "start_date": self.today.isoformat(),
            "end_date": "",
        }
        data.update(extra)
        return data

    def make_payment(self, **extra):
        data = dict(
            customer=self.customer, from_account=self.acc_a, to_account=self.acc_b,
            name="Rent", amount=Decimal("1000.00"), frequency="MONTHLY", category="RENT",
        )
        data.update(extra)
        payment = RecurringPayment(**data)
        payment.set_start(self.today)
        payment.save()
        return payment

    def loan_account(self):
        return Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="LOAN",
            status="ACTIVE", balance=Decimal("0.00"), daily_limit=Decimal("50000.00"),
        )


class AccessTests(PageBase):
    def test_anonymous_is_sent_to_login(self):
        for url in (self.list_url, self.new_url):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn("login", response.url)

    def test_staff_is_sent_away(self):
        self.login_staff()
        self.assertEqual(self.client.get(self.list_url).status_code, 302)
        self.assertEqual(self.client.get(self.new_url).status_code, 302)

    def test_customer_without_finished_kyc_can_look_but_not_create(self):
        self.login_customer("cust2")
        self.assertEqual(self.client.get(self.list_url).status_code, 200)
        self.assertEqual(self.client.get(self.new_url).status_code, 302)
        self.client.post(self.new_url, self.payload(from_account=self.acc_b.id, to_account_no=self.acc_a.account_no))
        self.assertEqual(RecurringPayment.objects.count(), 0)

    def test_frozen_customer_cannot_create(self):
        EmergencyFreeze.objects.create(customer=self.customer)
        self.login_customer()
        self.assertEqual(self.client.get(self.new_url).status_code, 302)
        self.client.post(self.new_url, self.payload())
        self.assertEqual(RecurringPayment.objects.count(), 0)


class ListTests(PageBase):
    def test_empty_list_says_so(self):
        self.login_customer()
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You have no recurring payments yet.")

    def test_list_shows_the_details(self):
        self.make_payment()
        self.login_customer()
        response = self.client.get(self.list_url)
        self.assertContains(response, "Rent")
        self.assertContains(response, "1000.00")
        self.assertContains(response, self.acc_b.account_no)
        self.assertContains(response, "Monthly")
        self.assertContains(response, "Active")

    def test_list_shows_last_result_and_failures(self):
        payment = self.make_payment()
        RecurringPayment.objects.filter(id=payment.id).update(
            status="PAUSED", consecutive_failures=3, last_result="Failed: Insufficient balance.",
        )
        self.login_customer()
        response = self.client.get(self.list_url)
        self.assertContains(response, "Insufficient balance")
        self.assertContains(response, "3 failed in a row")
        self.assertContains(response, "Paused")

    def test_other_customers_payments_are_hidden(self):
        self.make_payment(
            name="Secret", customer=self.customer2, from_account=self.acc_b, to_account=self.acc_a,
        )
        self.login_customer()
        self.assertNotContains(self.client.get(self.list_url), "Secret")

    def test_cancelled_payments_are_hidden(self):
        self.make_payment(name="Old plan", status="CANCELLED")
        self.login_customer()
        self.assertNotContains(self.client.get(self.list_url), "Old plan")


class CreateTests(PageBase):
    def post(self, **extra):
        self.login_customer()
        return self.client.post(self.new_url, self.payload(**extra))

    def test_form_offers_only_own_active_savings_and_current_accounts(self):
        loan = self.loan_account()
        self.login_customer()
        response = self.client.get(self.new_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.acc_a.account_no)
        self.assertNotContains(response, self.acc_b.account_no)
        self.assertNotContains(response, loan.account_no)

    def test_valid_payment_is_saved(self):
        response = self.post()
        self.assertEqual(response.status_code, 302)
        payment = RecurringPayment.objects.get()
        self.assertEqual(payment.customer_id, self.customer.id)
        self.assertEqual(payment.from_account_id, self.acc_a.id)
        self.assertEqual(payment.to_account_id, self.acc_b.id)
        self.assertEqual(payment.name, "Rent")
        self.assertEqual(payment.amount, Decimal("1000.00"))
        self.assertEqual(payment.category, "RENT")
        self.assertEqual(payment.frequency, "MONTHLY")
        self.assertEqual(payment.next_run_date, self.today)
        self.assertEqual(payment.anchor_day, self.today.day)
        self.assertEqual(payment.status, "ACTIVE")
        self.assertEqual(payment.consecutive_failures, 0)

    def test_end_date_can_be_set(self):
        end = self.today + timedelta(days=90)
        self.post(end_date=end.isoformat())
        self.assertEqual(RecurringPayment.objects.get().end_date, end)

    def test_weekly_payment_can_be_created(self):
        self.post(frequency="WEEKLY")
        self.assertEqual(RecurringPayment.objects.get().frequency, "WEEKLY")

    def test_unknown_destination_is_refused(self):
        response = self.post(to_account_no="NOPE-000")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No active account")
        self.assertEqual(RecurringPayment.objects.count(), 0)

    def test_closed_destination_is_refused(self):
        Account.objects.filter(id=self.acc_b.id).update(status="CLOSED")
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No active account")
        self.assertEqual(RecurringPayment.objects.count(), 0)

    def test_same_source_and_destination_is_refused(self):
        response = self.post(to_account_no=self.acc_a.account_no)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "different account")
        self.assertEqual(RecurringPayment.objects.count(), 0)

    def test_other_customers_source_account_is_refused(self):
        response = self.post(from_account=self.acc_b.id, to_account_no=self.acc_a.account_no)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(RecurringPayment.objects.count(), 0)

    def test_loan_source_account_is_refused(self):
        loan = self.loan_account()
        response = self.post(from_account=loan.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(RecurringPayment.objects.count(), 0)

    def test_amount_above_the_daily_limit_is_refused(self):
        response = self.post(amount="60000.00")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "daily limit")
        self.assertEqual(RecurringPayment.objects.count(), 0)

    def test_zero_amount_is_refused(self):
        response = self.post(amount="0")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(RecurringPayment.objects.count(), 0)

    def test_past_start_date_is_refused(self):
        response = self.post(start_date=(self.today - timedelta(days=1)).isoformat())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cannot be in the past")
        self.assertEqual(RecurringPayment.objects.count(), 0)

    def test_start_date_too_far_ahead_is_refused(self):
        response = self.post(start_date=(self.today + timedelta(days=400)).isoformat())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "within the next year")
        self.assertEqual(RecurringPayment.objects.count(), 0)

    def test_end_date_before_start_date_is_refused(self):
        response = self.post(
            start_date=(self.today + timedelta(days=5)).isoformat(),
            end_date=(self.today + timedelta(days=2)).isoformat(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cannot be before the first payment date")
        self.assertEqual(RecurringPayment.objects.count(), 0)

    def test_blank_name_is_refused(self):
        response = self.post(name="   ")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(RecurringPayment.objects.count(), 0)

    def test_eleventh_active_or_paused_payment_is_refused(self):
        for number in range(MAX_RECURRING_PAYMENTS - 1):
            self.make_payment(name=f"P{number}")
        self.make_payment(name="Paused one", status="PAUSED")
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"at most {MAX_RECURRING_PAYMENTS} recurring payments")
        self.assertEqual(RecurringPayment.objects.count(), MAX_RECURRING_PAYMENTS)

    def test_cancelled_and_ended_payments_do_not_count_towards_the_limit(self):
        for number in range(MAX_RECURRING_PAYMENTS - 1):
            self.make_payment(name=f"P{number}")
        for status in ("CANCELLED", "ENDED", "CANCELLED"):
            self.make_payment(name=f"Done {status}", status=status)
        response = self.post()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(RecurringPayment.objects.filter(name="Rent").count(), 1)

    def test_creation_is_audited(self):
        self.post()
        payment = RecurringPayment.objects.get()
        entry = AuditLog.objects.get(action=Actions.RECURRING_CREATED)
        self.assertEqual(entry.actor_username, "cust1")
        self.assertEqual(entry.target_type, "RECURRING_PAYMENT")
        self.assertEqual(entry.target_id, payment.id)
        self.assertIn("Rent", entry.details)

    def test_creating_a_payment_moves_no_money(self):
        before = self.balances()
        self.post()
        self.assertEqual(self.balances(), before)
        self.assertEqual(Transaction.objects.count(), 0)


class DashboardLinkTests(PageBase):
    def test_dashboard_links_to_recurring_payments(self):
        self.login_customer()
        response = self.client.get(reverse("customer_dashboard"))
        self.assertContains(response, self.list_url)