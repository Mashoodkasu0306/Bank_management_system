from datetime import datetime, timedelta
from decimal import Decimal

from django.utils import timezone

from loans.tests import add_repayment, make_loan
from planning.insights import build_insights
from planning.test_insights import InsightsBase
from transactions.models import Transaction
from users.spending import shift_month


class LoanBase(InsightsBase):
    def loan(self, **overrides):
        overrides.setdefault("emi_amount", Decimal("1000.00"))
        return make_loan(self.acc_a, self.customer, **overrides)

    def emi(self, loan, number, days, **extra):
        return add_repayment(loan, number, self.today + timedelta(days=days), **extra)

    def paid_at(self, days_ago):
        day = self.today - timedelta(days=days_ago)
        return timezone.make_aware(datetime(day.year, day.month, day.day, 12, 0))


class EmiInTheUpcomingListTests(LoanBase):
    def test_a_pending_emi_in_the_window_is_listed_and_subtracted(self):
        loan = self.loan()
        self.emi(loan, 1, 10)
        result = self.build()
        self.assertEqual(len(result["upcoming"]), 1)
        item = result["upcoming"][0]
        self.assertEqual(item["kind"], "EMI")
        self.assertIn(f"loan #{loan.id} EMI 1", item["label"])
        self.assertEqual(item["date"], self.today + timedelta(days=10))
        self.assertTrue(item["counted"])
        self.assertFalse(item["overdue"])
        self.assertEqual(result["upcoming_total"], Decimal("1000.00"))
        self.assertEqual(result["safe_to_spend"], Decimal("19000.00"))

    def test_an_emi_outside_the_window_is_ignored(self):
        self.emi(self.loan(), 1, 45)
        self.assertEqual(self.build()["upcoming"], [])

    def test_an_overdue_emi_is_listed_as_overdue(self):
        self.emi(self.loan(), 1, -5)
        item = self.build()["upcoming"][0]
        self.assertTrue(item["overdue"])
        self.assertTrue(item["counted"])

    def test_a_paid_emi_is_not_listed(self):
        self.emi(self.loan(), 1, 5, status="PAID", paid_date=self.paid_at(0))
        self.assertEqual(self.build()["upcoming"], [])

    def test_a_loan_that_is_not_approved_is_not_listed(self):
        self.emi(self.loan(status="PENDING"), 1, 5)
        self.assertEqual(self.build()["upcoming"], [])

    def test_other_customers_loans_are_ignored(self):
        other = make_loan(self.acc_b, self.customer2, emi_amount=Decimal("1000.00"))
        add_repayment(other, 1, self.today + timedelta(days=5))
        self.assertEqual(self.build()["upcoming"], [])

    def test_emis_and_recurring_payments_are_sorted_together(self):
        self.emi(self.loan(), 1, 5)
        self.due_in(self.make_payment(name="Rent"), 2)
        result = self.build()
        self.assertEqual([item["kind"] for item in result["upcoming"]], ["RECURRING", "EMI"])
        self.assertEqual(result["upcoming_total"], Decimal("2000.00"))


class DebtTests(LoanBase):
    def test_outstanding_is_the_amount_minus_the_principal_already_paid(self):
        loan = self.loan()
        self.emi(loan, 1, -30, status="PAID", paid_date=self.paid_at(30))
        self.emi(loan, 2, 10)
        debt = self.build()["debt"]
        self.assertEqual(len(debt["rows"]), 1)
        row = debt["rows"][0]
        self.assertEqual(row["id"], loan.id)
        self.assertEqual(row["outstanding"], Decimal("9000.00"))
        self.assertEqual(row["emi_amount"], Decimal("1000.00"))
        self.assertEqual(row["next_due"], self.today + timedelta(days=10))
        self.assertEqual(row["overdue_count"], 0)
        self.assertEqual(debt["total_outstanding"], Decimal("9000.00"))
        self.assertEqual(debt["monthly_emi_total"], Decimal("1000.00"))
        self.assertEqual(debt["status"], "OK")
        self.assertEqual(debt["label"], "On track")

    def test_an_overdue_emi_needs_attention(self):
        self.emi(self.loan(), 1, -3)
        debt = self.build()["debt"]
        row = debt["rows"][0]
        self.assertEqual(row["overdue_count"], 1)
        self.assertEqual(row["overdue_amount"], Decimal("1000.00"))
        self.assertEqual(row["days_overdue"], 3)
        self.assertEqual(debt["overdue_total"], Decimal("1000.00"))
        self.assertEqual(debt["status"], "ATTENTION")

    def test_a_defaulted_loan_needs_attention(self):
        self.emi(self.loan(status="DEFAULTED"), 1, 10)
        self.assertEqual(self.build()["debt"]["status"], "ATTENTION")

    def test_a_pending_application_is_not_debt(self):
        self.loan(status="PENDING")
        debt = self.build()["debt"]
        self.assertEqual(debt["rows"], [])
        self.assertEqual(debt["status"], "NONE")

    def test_a_fully_repaid_loan_is_skipped(self):
        loan = self.loan(amount=Decimal("1000.00"))
        self.emi(loan, 1, -5, status="PAID", paid_date=self.paid_at(5))
        self.assertEqual(self.build()["debt"]["rows"], [])

    def test_a_lump_sum_loan_uses_the_remaining_amount(self):
        make_loan(
            self.acc_a, self.customer, repayment_type="LUMP_SUM",
            lump_sum_total_payable=Decimal("11000.00"), lump_sum_paid=Decimal("4000.00"),
        )
        debt = self.build()["debt"]
        row = debt["rows"][0]
        self.assertEqual(row["outstanding"], Decimal("7000.00"))
        self.assertEqual(row["emi_amount"], Decimal("0.00"))
        self.assertIsNone(row["next_due"])
        self.assertEqual(debt["monthly_emi_total"], Decimal("0.00"))
        self.assertEqual(debt["status"], "OK")

    def test_a_fully_paid_lump_sum_loan_is_skipped(self):
        make_loan(
            self.acc_a, self.customer, repayment_type="LUMP_SUM",
            lump_sum_total_payable=Decimal("11000.00"), lump_sum_paid=Decimal("11000.00"),
        )
        self.assertEqual(self.build()["debt"]["rows"], [])

    def test_totals_add_up_over_several_loans(self):
        emi_loan = self.loan()
        self.emi(emi_loan, 1, 10)
        make_loan(
            self.acc_a, self.customer, repayment_type="LUMP_SUM",
            lump_sum_total_payable=Decimal("11000.00"), lump_sum_paid=Decimal("4000.00"),
        )
        debt = self.build()["debt"]
        self.assertEqual(len(debt["rows"]), 2)
        self.assertEqual(debt["total_outstanding"], Decimal("17000.00"))
        self.assertEqual(debt["monthly_emi_total"], Decimal("1000.00"))

    def test_emi_share_uses_the_average_income_of_the_three_previous_months(self):
        self.emi(self.loan(), 1, 10)
        for back in (1, 2, 3):
            year, month = shift_month(self.today.year, self.today.month, -back)
            deposit = Transaction.objects.create(
                transaction_type="DEPOSIT", to_account=self.acc_a, amount=Decimal("3000.00"),
                mode_of_transaction="CASH", status="SUCCESS", performed_by=self.cust_user, remarks="t",
            )
            when = timezone.make_aware(datetime(year, month, 15, 12, 0))
            Transaction.objects.filter(id=deposit.id).update(timestamp=when)
        self.assertEqual(self.build()["debt"]["emi_share_percent"], 33)

    def test_emi_share_is_empty_without_any_income(self):
        self.emi(self.loan(), 1, 10)
        self.assertIsNone(self.build()["debt"]["emi_share_percent"])