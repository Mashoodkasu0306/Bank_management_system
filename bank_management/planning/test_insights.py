from datetime import timedelta
from decimal import Decimal

from accounts.models import Account
from planning.insights import build_insights
from planning.models import RecurringPayment, SavingsGoal
from planning.test_recurring_pages import PageBase
from transactions.models import Transaction
from users.spending import shift_month


class InsightsBase(PageBase):
    def build(self, customer=None):
        return build_insights(customer or self.customer, today=self.today)

    def due_in(self, payment, days):
        RecurringPayment.objects.filter(id=payment.id).update(
            next_run_date=self.today + timedelta(days=days)
        )
        return payment

    def txn(self, from_account, to_account, amount, **extra):
        data = dict(
            transaction_type="TRANSFER", from_account=from_account, to_account=to_account,
            amount=Decimal(amount), mode_of_transaction="NETBANKING", status="SUCCESS",
            performed_by=self.cust_user, remarks="t", category="FOOD",
        )
        data.update(extra)
        return Transaction.objects.create(**data)

    def own_second_account(self):
        return Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="CURRENT",
            status="ACTIVE", balance=Decimal("100.00"), daily_limit=Decimal("50000.00"),
        )


class SafeToSpendTests(InsightsBase):
    def test_only_active_savings_and_current_accounts_count(self):
        self.loan_account()
        Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="CURRENT",
            status="CLOSED", balance=Decimal("500.00"), daily_limit=Decimal("50000.00"),
        )
        result = self.build()
        self.assertEqual(result["balance_total"], Decimal("20000.00"))
        self.assertEqual([a["account_no"] for a in result["accounts"]], [self.acc_a.account_no])

    def test_without_commitments_safe_to_spend_is_the_balance(self):
        result = self.build()
        self.assertEqual(result["upcoming"], [])
        self.assertEqual(result["upcoming_total"], Decimal("0.00"))
        self.assertEqual(result["safe_to_spend"], Decimal("20000.00"))
        self.assertFalse(result["shortfall"])

    def test_a_recurring_payment_in_the_window_is_subtracted(self):
        self.due_in(self.make_payment(), 3)
        result = self.build()
        self.assertEqual(len(result["upcoming"]), 1)
        self.assertEqual(result["upcoming"][0]["date"], self.today + timedelta(days=3))
        self.assertEqual(result["upcoming"][0]["kind"], "RECURRING")
        self.assertEqual(result["upcoming_total"], Decimal("1000.00"))
        self.assertEqual(result["safe_to_spend"], Decimal("19000.00"))

    def test_a_payment_outside_the_window_is_ignored(self):
        self.due_in(self.make_payment(), 40)
        result = self.build()
        self.assertEqual(result["upcoming"], [])
        self.assertEqual(result["safe_to_spend"], Decimal("20000.00"))

    def test_a_weekly_payment_counts_every_date_in_the_window(self):
        self.make_payment(frequency="WEEKLY")
        result = self.build()
        self.assertEqual(
            [item["date"] for item in result["upcoming"]],
            [self.today + timedelta(days=days) for days in (0, 7, 14, 21, 28)],
        )
        self.assertEqual(result["upcoming_total"], Decimal("5000.00"))
        self.assertEqual(result["safe_to_spend"], Decimal("15000.00"))

    def test_a_payment_to_your_own_account_is_listed_but_not_subtracted(self):
        second = self.own_second_account()
        self.due_in(self.make_payment(to_account=second), 3)
        result = self.build()
        self.assertEqual(len(result["upcoming"]), 1)
        self.assertFalse(result["upcoming"][0]["counted"])
        self.assertEqual(result["upcoming_total"], Decimal("0.00"))
        self.assertEqual(result["safe_to_spend"], Decimal("20100.00"))

    def test_paused_cancelled_and_ended_payments_are_not_listed(self):
        for status in ("PAUSED", "CANCELLED", "ENDED"):
            self.make_payment(name=status, status=status)
        self.assertEqual(self.build()["upcoming"], [])

    def test_the_end_date_cuts_the_list_short(self):
        self.make_payment(frequency="WEEKLY", end_date=self.today + timedelta(days=10))
        result = self.build()
        self.assertEqual(
            [item["date"] for item in result["upcoming"]],
            [self.today, self.today + timedelta(days=7)],
        )

    def test_a_payment_that_has_not_run_yet_counts_once_then_carries_on(self):
        payment = self.make_payment(frequency="WEEKLY")
        RecurringPayment.objects.filter(id=payment.id).update(
            next_run_date=self.today - timedelta(days=100)
        )
        result = self.build()
        self.assertEqual(len(result["upcoming"]), 5)
        self.assertTrue(result["upcoming"][0]["overdue"])
        self.assertFalse(any(item["overdue"] for item in result["upcoming"][1:]))
        self.assertEqual(result["upcoming_total"], Decimal("5000.00"))

    def test_a_shortfall_is_flagged(self):
        Account.objects.filter(id=self.acc_a.id).update(balance=Decimal("500.00"))
        self.due_in(self.make_payment(), 3)
        result = self.build()
        self.assertEqual(result["safe_to_spend"], Decimal("-500.00"))
        self.assertTrue(result["shortfall"])

    def test_other_customers_payments_are_ignored(self):
        self.make_payment(customer=self.customer2, from_account=self.acc_b, to_account=self.acc_a)
        self.assertEqual(self.build()["upcoming"], [])

    def test_upcoming_items_are_sorted_by_date(self):
        self.due_in(self.make_payment(name="Later"), 10)
        self.due_in(self.make_payment(name="Sooner"), 2)
        result = self.build()
        self.assertEqual([item["label"] for item in result["upcoming"]], ["Sooner", "Later"])


class CashFlowTests(InsightsBase):
    def test_six_months_oldest_first_ending_with_this_month(self):
        months = self.build()["months"]
        self.assertEqual(len(months), 6)
        first = shift_month(self.today.year, self.today.month, -5)
        self.assertEqual(months[0]["key"], f"{first[0]:04d}-{first[1]:02d}")
        self.assertEqual(months[-1]["key"], f"{self.today.year:04d}-{self.today.month:02d}")

    def test_amounts_come_from_the_spending_summary(self):
        self.txn(self.acc_a, self.acc_b, "100.00")
        self.assertEqual(self.build()["months"][-1]["out"], Decimal("100.00"))
        self.assertEqual(self.build(self.customer2)["months"][-1]["income"], Decimal("100.00"))

    def test_bars_are_relative_to_the_biggest_value(self):
        self.txn(self.acc_a, self.acc_b, "300.00")
        self.txn(self.acc_b, self.acc_a, "150.00")
        latest = self.build()["months"][-1]
        self.assertEqual(latest["out"], Decimal("300.00"))
        self.assertEqual(latest["income"], Decimal("150.00"))
        self.assertEqual(latest["out_pct"], 100)
        self.assertEqual(latest["income_pct"], 50)

    def test_empty_months_have_empty_bars(self):
        first = self.build()["months"][0]
        self.assertEqual((first["income_pct"], first["out_pct"]), (0, 0))


class OtherSectionTests(InsightsBase):
    def test_goals_are_included_with_progress(self):
        SavingsGoal.objects.create(
            customer=self.customer, account=self.acc_a, name="Holiday",
            target_amount=Decimal("50000.00"),
        )
        goals = self.build()["goals"]
        self.assertEqual(len(goals), 1)
        self.assertEqual(goals[0]["percent"], 40)

    def test_without_loans_the_debt_section_is_empty(self):
        debt = self.build()["debt"]
        self.assertEqual(debt["status"], "NONE")
        self.assertEqual(debt["label"], "No active loans")
        self.assertEqual(debt["rows"], [])
        self.assertEqual(debt["total_outstanding"], Decimal("0.00"))
        self.assertEqual(debt["monthly_emi_total"], Decimal("0.00"))
        self.assertIsNone(debt["emi_share_percent"])

    def test_building_insights_changes_nothing(self):
        payment = self.due_in(self.make_payment(), 3)
        before = (self.balances(), RecurringPayment.objects.get(id=payment.id).next_run_date)
        self.build()
        after = (self.balances(), RecurringPayment.objects.get(id=payment.id).next_run_date)
        self.assertEqual(before, after)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_today_defaults_to_the_real_date(self):
        result = build_insights(self.customer)
        self.assertEqual(result["today"], self.today)
        self.assertEqual(result["window_end"], self.today + timedelta(days=30))