from datetime import datetime
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from transactions.models import Transaction
from transactions.tests import TransactionTestBase
from users.spending import current_month, month_key, shift_month


class SpendingPageTests(TransactionTestBase):
    def setUp(self):
        super().setUp()
        self.url = reverse("my_spending_summary")
        self.year, self.month = current_month()

    def make(self, **extra):
        data = dict(
            transaction_type="TRANSFER", from_account=self.acc_a, to_account=self.acc_b,
            amount=Decimal("100.00"), mode_of_transaction="NETBANKING",
            status="SUCCESS", performed_by=self.cust_user, remarks="t",
            category="FOOD",
        )
        data.update(extra)
        return Transaction.objects.create(**data)

    # ---- who may open it ----
    def test_anonymous_is_sent_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_staff_cannot_open_it(self):
        self.login_staff()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_post_is_not_allowed(self):
        self.login_customer()
        self.assertEqual(self.client.post(self.url, {}).status_code, 405)

    # ---- what it shows ----
    def test_customer_sees_the_page_and_this_month(self):
        self.login_customer()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Spending Summary")
        self.assertContains(response, timezone.localdate().strftime("%B %Y"))

    def test_category_and_amount_are_shown(self):
        self.make()
        self.login_customer()
        response = self.client.get(self.url)
        self.assertContains(response, "Food")
        self.assertContains(response, "100.00")

    def test_bar_width_follows_the_share(self):
        self.make()
        self.login_customer()
        self.assertContains(self.client.get(self.url), "width:100%")

    def test_loan_payment_has_its_own_row(self):
        self.make(
            transaction_type="WITHDRAW", to_account=None, is_loan_related=True,
            amount=Decimal("500.00"),
        )
        self.login_customer()
        response = self.client.get(self.url)
        self.assertContains(response, "Loan payment")
        self.assertContains(response, "500.00")

    def test_customer_sees_only_their_own_numbers(self):
        self.make()
        self.login_customer("cust2")
        response = self.client.get(self.url)
        self.assertNotContains(response, "Food")
        self.assertContains(response, "No spending in this month.")

    def test_empty_month_says_so(self):
        self.login_customer()
        self.assertContains(self.client.get(self.url), "No spending in this month.")

    # ---- months ----
    def test_latest_month_has_a_previous_link_and_no_next_link(self):
        self.login_customer()
        prev_year, prev_month = shift_month(self.year, self.month, -1)
        response = self.client.get(self.url)
        self.assertContains(response, "?month=" + month_key(prev_year, prev_month))
        self.assertNotContains(response, "Next month")

    def test_earlier_month_shows_its_own_data_and_a_next_link(self):
        txn = self.make()
        prev_year, prev_month = shift_month(self.year, self.month, -1)
        when = timezone.make_aware(datetime(prev_year, prev_month, 15, 12, 0))
        Transaction.objects.filter(id=txn.id).update(timestamp=when)
        self.login_customer()
        response = self.client.get(self.url, {"month": month_key(prev_year, prev_month)})
        self.assertContains(response, "Food")
        self.assertContains(response, "?month=" + month_key(self.year, self.month))
        this_month = self.client.get(self.url)
        self.assertNotContains(this_month, "Food")

    def test_future_month_falls_back_to_this_month(self):
        self.login_customer()
        future = shift_month(self.year, self.month, 2)
        response = self.client.get(self.url, {"month": month_key(*future)})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, timezone.localdate().strftime("%B %Y"))

    def test_junk_month_does_not_crash(self):
        self.login_customer()
        for text in ("abc", "2025-99", "", "../../x"):
            self.assertEqual(self.client.get(self.url, {"month": text}).status_code, 200)

    # ---- link ----
    def test_dashboard_links_to_the_page(self):
        self.login_customer()
        response = self.client.get(reverse("customer_dashboard"))
        self.assertContains(response, self.url)