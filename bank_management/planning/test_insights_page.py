from decimal import Decimal

from django.urls import reverse

from accounts.models import Account
from loans.tests import add_repayment, make_loan
from planning.models import RecurringPayment, SavingsGoal
from planning.test_insights_loans import LoanBase
from transactions.models import Transaction


class InsightsPageBase(LoanBase):
    def setUp(self):
        super().setUp()
        self.url = reverse("my_insights")

    def open(self, username="cust1"):
        self.login_customer(username)
        return self.client.get(self.url)


class AccessTests(InsightsPageBase):
    def test_anonymous_is_sent_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_staff_is_sent_away(self):
        self.login_staff()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_customer_can_open_the_page(self):
        response = self.open()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Money Insights")

    def test_post_is_not_allowed(self):
        self.login_customer()
        self.assertEqual(self.client.post(self.url).status_code, 405)


class SafeToSpendTests(InsightsPageBase):
    def test_shows_the_balance_and_safe_to_spend(self):
        response = self.open()
        self.assertContains(response, "Safe to spend")
        self.assertContains(response, "20000.00")

    def test_what_is_due_is_subtracted(self):
        self.due_in(self.make_payment(), 3)
        self.assertContains(self.open(), "19000.00")

    def test_a_shortfall_is_warned_about(self):
        Account.objects.filter(id=self.acc_a.id).update(balance=Decimal("500.00"))
        self.due_in(self.make_payment(), 3)
        response = self.open()
        self.assertContains(response, "more than your balance")
        self.assertContains(response, "-500.00")

    def test_there_is_no_warning_when_there_is_enough(self):
        self.due_in(self.make_payment(), 3)
        self.assertNotContains(self.open(), "more than your balance")


class UpcomingTests(InsightsPageBase):
    def test_recurring_payments_and_emis_are_listed(self):
        self.due_in(self.make_payment(name="Rent"), 2)
        self.emi(self.loan(), 1, 5)
        response = self.open()
        self.assertContains(response, "Rent")
        self.assertContains(response, "EMI 1")

    def test_an_overdue_emi_is_marked(self):
        self.emi(self.loan(), 1, -5)
        self.assertContains(self.open(), "Overdue")

    def test_a_payment_between_your_own_accounts_is_marked_not_subtracted(self):
        second = self.own_second_account()
        self.due_in(self.make_payment(to_account=second), 3)
        self.assertContains(self.open(), "not subtracted")

    def test_an_empty_list_says_so(self):
        self.assertContains(self.open(), "Nothing is due in the next 30 days.")


class CashFlowTests(InsightsPageBase):
    def test_every_month_links_to_its_spending_summary(self):
        months = self.build()["months"]
        response = self.open()
        self.assertContains(response, "?month=" + months[0]["key"])
        self.assertContains(response, "?month=" + months[-1]["key"])

    def test_the_biggest_bar_is_full_width(self):
        self.txn(self.acc_a, self.acc_b, "300.00")
        self.assertContains(self.open(), "width:100%")


class GoalTests(InsightsPageBase):
    def test_a_goal_is_shown_with_its_progress(self):
        SavingsGoal.objects.create(
            customer=self.customer, account=self.acc_a, name="Holiday",
            target_amount=Decimal("50000.00"),
        )
        response = self.open()
        self.assertContains(response, "Holiday")
        self.assertContains(response, "40% funded")

    def test_without_goals_it_says_so(self):
        self.assertContains(self.open(), "no savings goals")


class LoanTests(InsightsPageBase):
    def test_without_loans_it_says_so(self):
        response = self.open()
        self.assertContains(response, "No active loans")
        self.assertContains(response, "You have no active loans.")

    def test_a_loan_is_shown_with_what_is_left_and_its_status(self):
        loan = self.loan()
        self.emi(loan, 1, -30, status="PAID", paid_date=self.paid_at(30))
        self.emi(loan, 2, 10)
        response = self.open()
        self.assertContains(response, "9000.00")
        self.assertContains(response, "On track")

    def test_an_overdue_loan_needs_attention(self):
        self.emi(self.loan(), 1, -3)
        response = self.open()
        self.assertContains(response, "Needs attention")
        self.assertContains(response, "1 overdue")

    def test_a_lump_sum_loan_shows_what_remains(self):
        make_loan(
            self.acc_a, self.customer, repayment_type="LUMP_SUM",
            lump_sum_total_payable=Decimal("11000.00"), lump_sum_paid=Decimal("4000.00"),
        )
        self.assertContains(self.open(), "7000.00")


class PrivacyAndLinkTests(InsightsPageBase):
    def test_other_customers_data_is_not_shown(self):
        self.make_payment(
            name="Secret", customer=self.customer2, from_account=self.acc_b, to_account=self.acc_a,
        )
        other = make_loan(self.acc_b, self.customer2, emi_amount=Decimal("1000.00"))
        add_repayment(other, 1, self.today)
        response = self.open()
        self.assertNotContains(response, "Secret")
        self.assertContains(response, "You have no active loans.")

    def test_the_dashboard_links_to_the_page(self):
        self.login_customer()
        response = self.client.get(reverse("customer_dashboard"))
        self.assertContains(response, self.url)

    def test_viewing_the_page_changes_nothing(self):
        payment = self.due_in(self.make_payment(), 3)
        before = (self.balances(), RecurringPayment.objects.get(id=payment.id).next_run_date)
        self.open()
        after = (self.balances(), RecurringPayment.objects.get(id=payment.id).next_run_date)
        self.assertEqual(before, after)
        self.assertEqual(Transaction.objects.count(), 0)