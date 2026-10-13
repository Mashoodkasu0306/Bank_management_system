from datetime import datetime
from decimal import Decimal

from django.test import SimpleTestCase
from django.utils import timezone

from accounts.models import Account
from transactions.models import Transaction
from transactions.tests import TransactionTestBase
from users.spending import (
    current_month, month_key, month_summary, parse_month, shift_month,
)


class MonthHelperTests(SimpleTestCase):
    def test_valid_month_is_read(self):
        year, month = current_month()
        self.assertEqual(parse_month(month_key(year, month)), (year, month))
        self.assertEqual(parse_month("2025-03"), (2025, 3))

    def test_odd_values_give_this_month(self):
        for text in ("", "abc", "2025", "2025-13", "2025-00", "99999-01", "1990-05", "2025-3-1"):
            self.assertEqual(parse_month(text), current_month(), text)

    def test_missing_value_gives_this_month(self):
        self.assertEqual(parse_month(None), current_month())

    def test_future_month_gives_this_month(self):
        year, month = current_month()
        future = shift_month(year, month, 1)
        self.assertEqual(parse_month(month_key(*future)), (year, month))

    def test_shift_month_wraps_the_year(self):
        self.assertEqual(shift_month(2026, 1, -1), (2025, 12))
        self.assertEqual(shift_month(2025, 12, 1), (2026, 1))
        self.assertEqual(shift_month(2026, 5, 0), (2026, 5))


class SpendingDataTests(TransactionTestBase):
    def setUp(self):
        super().setUp()
        self.year, self.month = current_month()

    def make(self, **extra):
        data = dict(
            transaction_type="TRANSFER", from_account=self.acc_a, to_account=self.acc_b,
            amount=Decimal("100.00"), mode_of_transaction="NETBANKING",
            status="SUCCESS", performed_by=self.cust_user, remarks="t",
        )
        data.update(extra)
        return Transaction.objects.create(**data)

    def summary(self, customer=None, year=None, month=None):
        return month_summary(customer or self.customer, year or self.year, month or self.month)

    def amounts(self, result):
        return {row["code"]: row["amount"] for row in result["rows"]}

    def test_spending_is_grouped_by_category_biggest_first(self):
        self.make(category="TRAVEL", amount=Decimal("30.00"))
        self.make(category="FOOD", amount=Decimal("100.00"))
        self.make(category="FOOD", amount=Decimal("50.00"))
        result = self.summary()
        self.assertEqual([row["code"] for row in result["rows"]], ["FOOD", "TRAVEL"])
        self.assertEqual(self.amounts(result), {"FOOD": Decimal("150.00"), "TRAVEL": Decimal("30.00")})
        self.assertEqual(result["total_out"], Decimal("180.00"))
        self.assertEqual(result["rows"][0]["label"], "Food")

    def test_receiver_gets_income_and_no_category(self):
        self.make(category="FOOD", amount=Decimal("100.00"))
        result = self.summary(self.customer2)
        self.assertEqual(result["income"], Decimal("100.00"))
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["total_out"], Decimal("0.00"))

    def test_failed_and_pending_are_left_out(self):
        self.make(status="FAILED", category="FOOD")
        self.make(status="PENDING", category="FOOD")
        result = self.summary()
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["total_out"], Decimal("0.00"))

    def test_transfer_between_own_accounts_is_left_out(self):
        second = Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="CURRENT",
            status="ACTIVE", balance=Decimal("100.00"), daily_limit=Decimal("50000.00"),
        )
        self.make(to_account=second, category="FOOD")
        result = self.summary()
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["income"], Decimal("0.00"))
        self.assertEqual(result["own_transfers"], 1)

    def test_loan_payment_goes_to_its_own_bucket(self):
        self.make(
            transaction_type="WITHDRAW", to_account=None, is_loan_related=True,
            category="FOOD", amount=Decimal("500.00"),
        )
        result = self.summary()
        self.assertEqual(self.amounts(result), {"LOAN_PAYMENT": Decimal("500.00")})
        self.assertEqual(result["rows"][0]["label"], "Loan payment")

    def test_loan_money_received_is_not_income(self):
        self.make(
            transaction_type="DEPOSIT", from_account=None, to_account=self.acc_a,
            is_loan_related=True, amount=Decimal("10000.00"),
        )
        result = self.summary()
        self.assertEqual(result["loan_received"], Decimal("10000.00"))
        self.assertEqual(result["income"], Decimal("0.00"))

    def test_deposit_counts_as_income(self):
        self.make(
            transaction_type="DEPOSIT", from_account=None, to_account=self.acc_a,
            amount=Decimal("2000.00"),
        )
        result = self.summary()
        self.assertEqual(result["income"], Decimal("2000.00"))
        self.assertEqual(result["loan_received"], Decimal("0.00"))

    def test_other_months_are_left_out(self):
        txn = self.make(category="FOOD")
        prev_year, prev_month = shift_month(self.year, self.month, -1)
        when = timezone.make_aware(datetime(prev_year, prev_month, 15, 12, 0))
        Transaction.objects.filter(id=txn.id).update(timestamp=when)
        self.assertEqual(self.summary()["rows"], [])
        earlier = self.summary(year=prev_year, month=prev_month)
        self.assertEqual(self.amounts(earlier), {"FOOD": Decimal("100.00")})

    def test_single_category_is_100_percent(self):
        self.make(category="FOOD")
        self.assertEqual(self.summary()["rows"][0]["percent"], 100)

    def test_percentages_follow_the_amounts(self):
        self.make(category="FOOD", amount=Decimal("300.00"))
        self.make(category="BILLS", amount=Decimal("100.00"))
        percents = {row["code"]: row["percent"] for row in self.summary()["rows"]}
        self.assertEqual(percents, {"FOOD": 75, "BILLS": 25})

    def test_net_is_income_minus_spending(self):
        self.make(category="FOOD", amount=Decimal("100.00"))
        self.make(
            transaction_type="DEPOSIT", from_account=None, to_account=self.acc_a,
            amount=Decimal("350.00"),
        )
        result = self.summary()
        self.assertEqual(result["net"], Decimal("250.00"))

    def test_month_links(self):
        prev_year, prev_month = shift_month(self.year, self.month, -1)
        result = self.summary()
        self.assertIsNone(result["next_key"])
        self.assertEqual(result["prev_key"], month_key(prev_year, prev_month))
        earlier = self.summary(year=prev_year, month=prev_month)
        self.assertEqual(earlier["next_key"], month_key(self.year, self.month))