from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse

from accounts.models import Account
from planning.goals import goal_progress, goals_for
from planning.models import SavingsGoal
from transactions.models import Transaction
from transactions.tests import TransactionTestBase


class GoalBase(TransactionTestBase):
    def make_goal(self, **extra):
        data = dict(
            customer=self.customer, account=self.acc_a, name="Holiday",
            target_amount=Decimal("50000.00"),
        )
        data.update(extra)
        return SavingsGoal.objects.create(**data)

    def set_balance(self, amount):
        Account.objects.filter(id=self.acc_a.id).update(balance=Decimal(amount))
        self.acc_a.refresh_from_db()


class ModelRuleTests(GoalBase):
    def candidate(self, **extra):
        data = dict(
            customer=self.customer, account=self.acc_a, name="Holiday",
            target_amount=Decimal("50000.00"),
        )
        data.update(extra)
        return SavingsGoal(**data)

    def test_goal_on_own_savings_account_is_valid(self):
        self.candidate().full_clean()

    def test_goal_on_own_current_account_is_valid(self):
        current = Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="CURRENT",
            status="ACTIVE", balance=Decimal("100.00"), daily_limit=Decimal("50000.00"),
        )
        self.candidate(account=current).full_clean()

    def test_goal_on_someone_elses_account_is_refused(self):
        with self.assertRaises(ValidationError) as caught:
            self.candidate(account=self.acc_b).full_clean()
        self.assertIn("account", caught.exception.message_dict)

    def test_goal_on_loan_account_is_refused(self):
        loan = Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="LOAN",
            status="ACTIVE", balance=Decimal("0.00"), daily_limit=Decimal("50000.00"),
        )
        with self.assertRaises(ValidationError) as caught:
            self.candidate(account=loan).full_clean()
        self.assertIn("account", caught.exception.message_dict)

    def test_target_must_be_above_zero(self):
        for amount in ("0.00", "-5.00"):
            with self.assertRaises(ValidationError) as caught:
                self.candidate(target_amount=Decimal(amount)).full_clean()
            self.assertIn("target_amount", caught.exception.message_dict)

    def test_name_is_required(self):
        with self.assertRaises(ValidationError) as caught:
            self.candidate(name="").full_clean()
        self.assertIn("name", caught.exception.message_dict)


class ProgressTests(GoalBase):
    def test_80_percent_funded_is_not_an_error(self):
        self.set_balance("40000.00")
        result = goal_progress(self.make_goal())
        self.assertEqual(result["percent"], 80)
        self.assertEqual(result["saved"], Decimal("40000.00"))
        self.assertEqual(result["remaining"], Decimal("10000.00"))
        self.assertFalse(result["achieved"])

    def test_zero_balance_is_zero_percent(self):
        self.set_balance("0.00")
        result = goal_progress(self.make_goal())
        self.assertEqual(result["percent"], 0)
        self.assertEqual(result["saved"], Decimal("0.00"))
        self.assertEqual(result["remaining"], Decimal("50000.00"))

    def test_percent_rounds_down(self):
        self.set_balance("9999.00")
        result = goal_progress(self.make_goal(target_amount=Decimal("10000.00")))
        self.assertEqual(result["percent"], 99)
        self.assertFalse(result["achieved"])

    def test_above_target_is_capped_at_100(self):
        self.set_balance("60000.00")
        result = goal_progress(self.make_goal())
        self.assertEqual(result["percent"], 100)
        self.assertEqual(result["saved"], Decimal("50000.00"))
        self.assertEqual(result["remaining"], Decimal("0.00"))
        self.assertTrue(result["achieved"])

    def test_exactly_on_target_is_achieved(self):
        self.set_balance("50000.00")
        result = goal_progress(self.make_goal())
        self.assertEqual(result["percent"], 100)
        self.assertTrue(result["achieved"])

    def test_days_left_counts_down_to_the_target_date(self):
        goal = self.make_goal(target_date=date(2026, 10, 24))
        result = goal_progress(goal, today=date(2026, 10, 14))
        self.assertEqual(result["days_left"], 10)
        self.assertFalse(result["overdue"])

    def test_past_date_and_not_achieved_is_overdue(self):
        goal = self.make_goal(target_date=date(2026, 10, 1))
        result = goal_progress(goal, today=date(2026, 10, 14))
        self.assertEqual(result["days_left"], 0)
        self.assertTrue(result["overdue"])

    def test_past_date_but_achieved_is_not_overdue(self):
        self.set_balance("60000.00")
        goal = self.make_goal(target_date=date(2026, 10, 1))
        result = goal_progress(goal, today=date(2026, 10, 14))
        self.assertTrue(result["achieved"])
        self.assertFalse(result["overdue"])

    def test_no_date_means_no_days_left(self):
        result = goal_progress(self.make_goal())
        self.assertIsNone(result["days_left"])
        self.assertFalse(result["overdue"])

    def test_closed_account_is_flagged(self):
        goal = self.make_goal()
        Account.objects.filter(id=self.acc_a.id).update(status="CLOSED")
        goal = SavingsGoal.objects.select_related("account").get(id=goal.id)
        self.assertFalse(goal_progress(goal)["account_active"])


class GoalsForTests(GoalBase):
    def test_only_active_goals_of_this_customer(self):
        mine = self.make_goal(name="Mine")
        self.make_goal(name="Old", status="ARCHIVED")
        self.make_goal(name="Theirs", customer=self.customer2, account=self.acc_b)
        entries = goals_for(self.customer)
        self.assertEqual([e["goal"].id for e in entries], [mine.id])

    def test_goals_are_in_creation_order(self):
        self.make_goal(name="A")
        self.make_goal(name="B")
        self.assertEqual([e["goal"].name for e in goals_for(self.customer)], ["A", "B"])

    def test_progress_follows_the_live_balance(self):
        self.make_goal()
        self.assertEqual(goals_for(self.customer)[0]["percent"], 40)
        Account.objects.filter(id=self.acc_a.id).update(balance=Decimal("40000.00"))
        self.assertEqual(goals_for(self.customer)[0]["percent"], 80)

    def test_no_goals_gives_empty_list(self):
        self.assertEqual(goals_for(self.customer), [])


class TrackingOnlyTests(GoalBase):
    def test_goal_never_blocks_or_moves_money(self):
        self.make_goal(target_amount=Decimal("50000.00"))
        self.login_staff()
        self.client.post(reverse("transfer"), {
            "from_account_no": self.acc_a.account_no,
            "to_account_no": self.acc_b.account_no,
            "amount": "15000.00",
        })
        a, b = self.balances()
        self.assertEqual(a, Decimal("5000.00"))
        self.assertEqual(b, Decimal("20000.00"))
        self.assertEqual(Transaction.objects.get().status, "SUCCESS")
        self.assertEqual(goals_for(self.customer)[0]["percent"], 10)