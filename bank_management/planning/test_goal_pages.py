from datetime import date
from decimal import Decimal

from django.urls import reverse

from accounts.models import Account
from planning.forms import MAX_ACTIVE_GOALS
from planning.models import SavingsGoal
from transactions.tests import TransactionTestBase


class GoalPageBase(TransactionTestBase):
    def goal(self, **extra):
        data = dict(
            customer=self.customer, account=self.acc_a, name="Holiday",
            target_amount=Decimal("50000.00"),
        )
        data.update(extra)
        return SavingsGoal.objects.create(**data)

    def payload(self, **extra):
        data = {
            "account": self.acc_a.id, "name": "Car", "target_amount": "25000.00",
            "target_date": "2099-01-01",
        }
        data.update(extra)
        return data

    def set_balance(self, amount):
        Account.objects.filter(id=self.acc_a.id).update(balance=Decimal(amount))

    def loan_account(self):
        return Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="LOAN",
            status="ACTIVE", balance=Decimal("0.00"), daily_limit=Decimal("50000.00"),
        )


class AccessTests(GoalPageBase):
    def test_anonymous_is_sent_to_login(self):
        for url in (reverse("my_goals"), reverse("goal_create")):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn("login", response.url)
        goal = self.goal()
        response = self.client.post(reverse("goal_archive", args=[goal.id]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_staff_is_sent_away(self):
        goal = self.goal()
        self.login_staff()
        for url in (
            reverse("my_goals"), reverse("goal_create"), reverse("goal_edit", args=[goal.id]),
        ):
            self.assertEqual(self.client.get(url).status_code, 302)
        self.assertEqual(
            self.client.post(reverse("goal_archive", args=[goal.id])).status_code, 302
        )
        goal.refresh_from_db()
        self.assertEqual(goal.status, "ACTIVE")


class ListTests(GoalPageBase):
    def test_empty_list_says_so(self):
        self.login_customer()
        response = self.client.get(reverse("my_goals"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You have no savings goals yet.")

    def test_goal_shows_name_percent_and_amount_to_go(self):
        self.goal()
        self.set_balance("40000.00")
        self.login_customer()
        response = self.client.get(reverse("my_goals"))
        self.assertContains(response, "Holiday")
        self.assertContains(response, "80% funded")
        self.assertContains(response, "to go")
        self.assertNotContains(response, "Goal reached!")

    def test_reached_goal_is_celebrated(self):
        self.goal()
        self.set_balance("60000.00")
        self.login_customer()
        response = self.client.get(reverse("my_goals"))
        self.assertContains(response, "100% funded")
        self.assertContains(response, "Goal reached!")

    def test_overdue_goal_is_flagged(self):
        self.goal(target_date=date(2020, 1, 1))
        self.login_customer()
        self.assertContains(self.client.get(reverse("my_goals")), "Target date has passed")

    def test_other_customers_goals_are_hidden(self):
        self.goal(name="Secret", customer=self.customer2, account=self.acc_b)
        self.login_customer()
        self.assertNotContains(self.client.get(reverse("my_goals")), "Secret")

    def test_archived_goals_are_hidden(self):
        self.goal(name="Old plan", status="ARCHIVED")
        self.login_customer()
        self.assertNotContains(self.client.get(reverse("my_goals")), "Old plan")

    def test_closed_account_is_warned_about(self):
        self.goal()
        Account.objects.filter(id=self.acc_a.id).update(status="CLOSED")
        self.login_customer()
        self.assertContains(self.client.get(reverse("my_goals")), "account is closed")


class CreateTests(GoalPageBase):
    def test_form_offers_only_own_active_savings_and_current_accounts(self):
        loan = self.loan_account()
        self.login_customer()
        response = self.client.get(reverse("goal_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.acc_a.account_no)
        self.assertNotContains(response, self.acc_b.account_no)
        self.assertNotContains(response, loan.account_no)

    def test_valid_goal_is_saved_for_this_customer(self):
        self.login_customer()
        response = self.client.post(reverse("goal_create"), self.payload())
        self.assertEqual(response.status_code, 302)
        goal = SavingsGoal.objects.get()
        self.assertEqual(goal.customer_id, self.customer.id)
        self.assertEqual(goal.account_id, self.acc_a.id)
        self.assertEqual(goal.name, "Car")
        self.assertEqual(goal.target_amount, Decimal("25000.00"))
        self.assertEqual(goal.target_date, date(2099, 1, 1))
        self.assertEqual(goal.status, "ACTIVE")

    def test_date_is_optional(self):
        self.login_customer()
        self.client.post(reverse("goal_create"), self.payload(target_date=""))
        self.assertIsNone(SavingsGoal.objects.get().target_date)

    def test_other_customers_account_is_refused(self):
        self.login_customer()
        response = self.client.post(reverse("goal_create"), self.payload(account=self.acc_b.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(SavingsGoal.objects.count(), 0)

    def test_loan_account_is_refused(self):
        loan = self.loan_account()
        self.login_customer()
        response = self.client.post(reverse("goal_create"), self.payload(account=loan.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(SavingsGoal.objects.count(), 0)

    def test_zero_or_negative_target_is_refused(self):
        self.login_customer()
        for amount in ("0", "0.00", "-10"):
            response = self.client.post(reverse("goal_create"), self.payload(target_amount=amount))
            self.assertEqual(response.status_code, 200, amount)
        self.assertEqual(SavingsGoal.objects.count(), 0)

    def test_past_date_is_refused(self):
        self.login_customer()
        response = self.client.post(reverse("goal_create"), self.payload(target_date="2020-01-01"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cannot be in the past")
        self.assertEqual(SavingsGoal.objects.count(), 0)

    def test_blank_name_is_refused(self):
        self.login_customer()
        response = self.client.post(reverse("goal_create"), self.payload(name="   "))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(SavingsGoal.objects.count(), 0)

    def test_eleventh_active_goal_is_refused(self):
        for number in range(MAX_ACTIVE_GOALS):
            self.goal(name=f"Goal {number}")
        self.login_customer()
        response = self.client.post(reverse("goal_create"), self.payload())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"at most {MAX_ACTIVE_GOALS} active goals")
        self.assertEqual(SavingsGoal.objects.count(), MAX_ACTIVE_GOALS)

    def test_creating_a_goal_does_not_touch_the_balance(self):
        before = self.balances()
        self.login_customer()
        self.client.post(reverse("goal_create"), self.payload())
        self.assertEqual(self.balances(), before)


class EditTests(GoalPageBase):
    def test_owner_can_change_the_goal(self):
        goal = self.goal()
        self.login_customer()
        response = self.client.post(
            reverse("goal_edit", args=[goal.id]),
            self.payload(name="Car fund", target_amount="60000.00", target_date=""),
        )
        self.assertEqual(response.status_code, 302)
        goal.refresh_from_db()
        self.assertEqual(goal.name, "Car fund")
        self.assertEqual(goal.target_amount, Decimal("60000.00"))
        self.assertIsNone(goal.target_date)

    def test_other_customer_gets_404(self):
        goal = self.goal()
        self.login_customer("cust2")
        url = reverse("goal_edit", args=[goal.id])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, self.payload(name="Hacked")).status_code, 404)
        goal.refresh_from_db()
        self.assertEqual(goal.name, "Holiday")

    def test_archived_goal_gets_404(self):
        goal = self.goal(status="ARCHIVED")
        self.login_customer()
        self.assertEqual(self.client.get(reverse("goal_edit", args=[goal.id])).status_code, 404)

    def test_unchanged_past_date_is_allowed(self):
        goal = self.goal(target_date=date(2020, 1, 1))
        self.login_customer()
        response = self.client.post(
            reverse("goal_edit", args=[goal.id]),
            self.payload(name="Renamed", target_date="2020-01-01"),
        )
        self.assertEqual(response.status_code, 302)
        goal.refresh_from_db()
        self.assertEqual(goal.name, "Renamed")

    def test_new_past_date_is_refused(self):
        goal = self.goal()
        self.login_customer()
        response = self.client.post(
            reverse("goal_edit", args=[goal.id]), self.payload(target_date="2020-01-01")
        )
        self.assertEqual(response.status_code, 200)
        goal.refresh_from_db()
        self.assertIsNone(goal.target_date)

    def test_edit_form_shows_the_current_values(self):
        goal = self.goal(name="Wedding")
        self.login_customer()
        response = self.client.get(reverse("goal_edit", args=[goal.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Wedding")


class ArchiveTests(GoalPageBase):
    def test_archive_hides_the_goal(self):
        goal = self.goal()
        self.login_customer()
        response = self.client.post(reverse("goal_archive", args=[goal.id]))
        self.assertEqual(response.status_code, 302)
        goal.refresh_from_db()
        self.assertEqual(goal.status, "ARCHIVED")
        self.assertNotContains(self.client.get(reverse("my_goals")), "Holiday")

    def test_get_is_not_allowed(self):
        goal = self.goal()
        self.login_customer()
        self.assertEqual(self.client.get(reverse("goal_archive", args=[goal.id])).status_code, 405)

    def test_other_customer_gets_404(self):
        goal = self.goal()
        self.login_customer("cust2")
        self.assertEqual(self.client.post(reverse("goal_archive", args=[goal.id])).status_code, 404)
        goal.refresh_from_db()
        self.assertEqual(goal.status, "ACTIVE")

    def test_archiving_does_not_touch_the_balance(self):
        goal = self.goal()
        before = self.balances()
        self.login_customer()
        self.client.post(reverse("goal_archive", args=[goal.id]))
        self.assertEqual(self.balances(), before)


class DashboardLinkTests(GoalPageBase):
    def test_dashboard_links_to_goals(self):
        self.login_customer()
        response = self.client.get(reverse("customer_dashboard"))
        self.assertContains(response, reverse("my_goals"))