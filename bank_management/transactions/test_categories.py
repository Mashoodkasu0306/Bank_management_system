from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse

from transactions.models import Transaction
from transactions.tests import TransactionTestBase

EXPECTED_CATEGORIES = {
    "FOOD", "SHOPPING", "BILLS", "RENT", "TRAVEL",
    "HEALTH", "EDUCATION", "ENTERTAINMENT", "SAVINGS", "OTHER",
}


class TransactionCategoryTests(TransactionTestBase):
    def make_txn(self, **extra):
        data = dict(
            transaction_type="DEPOSIT", to_account=self.acc_a, amount=Decimal("10.00"),
            mode_of_transaction="CASH", status="SUCCESS",
        )
        data.update(extra)
        return Transaction(**data)

    def test_new_transaction_defaults_to_other(self):
        txn = self.make_txn()
        txn.save()
        txn.refresh_from_db()
        self.assertEqual(txn.category, "OTHER")

    def test_category_choices_are_the_agreed_list(self):
        codes = {code for code, _label in Transaction.CATEGORY_CHOICES}
        self.assertEqual(codes, EXPECTED_CATEGORIES)
        self.assertTrue(all(len(code) <= 20 for code in codes))

    def test_a_valid_category_passes_validation(self):
        self.make_txn(category="FOOD").full_clean()

    def test_an_unknown_category_fails_validation(self):
        with self.assertRaises(ValidationError):
            self.make_txn(category="PIRATES").full_clean()

    def test_staff_deposit_still_works_and_gets_other(self):
        self.login_staff()
        self.client.post(reverse("deposit"), {
            "account_no": self.acc_a.account_no, "amount": "1500.00",
        })
        txn = Transaction.objects.get(to_account=self.acc_a)
        self.assertEqual(txn.status, "SUCCESS")
        self.assertEqual(txn.category, "OTHER")