from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from core.validators import MAX_AMOUNT, parse_money


class ParseMoneyTests(SimpleTestCase):
    def test_normal_amounts_are_accepted(self):
        self.assertEqual(parse_money("100"), Decimal("100"))
        self.assertEqual(parse_money(" 2500.50 "), Decimal("2500.50"))
        self.assertEqual(parse_money("0.01"), Decimal("0.01"))
        self.assertEqual(parse_money("5.500"), Decimal("5.5"))

    def test_bad_values_are_refused(self):
        bad = [
            None, "", "   ", "abc", "1,000", "NaN", "nan", "Infinity", "-Infinity",
            "1e999999", "0.001", "5.005", "9" * 40, "100000000.01",
        ]
        for raw in bad:
            with self.subTest(raw=raw):
                with self.assertRaises(InvalidOperation):
                    parse_money(raw)

    def test_the_cap_itself_is_allowed(self):
        self.assertEqual(parse_money("100000000.00"), MAX_AMOUNT)

    def test_zero_and_negative_are_left_to_the_views(self):
        self.assertEqual(parse_money("0"), 0)
        self.assertEqual(parse_money("-5"), -5)


class ViewsUseTheSharedCheckTests(SimpleTestCase):
    def test_no_raw_decimal_parsing_of_amounts_is_left(self):
        for rel in ("transactions/views.py", "loans/views.py"):
            source = (Path(settings.BASE_DIR) / rel).read_text(encoding="utf-8")
            self.assertNotIn("Decimal(amount_raw)", source, rel)
            self.assertIn("parse_money(amount_raw)", source, rel)