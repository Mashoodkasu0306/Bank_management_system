from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import SimpleTestCase


class FakeUser:
    username = "customer_1"

    def get_full_name(self):
        return ""


def fake_card(**overrides):
    values = dict(
        status="APPROVED",
        freeze_state="",
        masked_card_number="1234 4321 1324 243",
        card_type="DEBIT",
        account=SimpleNamespace(customer=SimpleNamespace(user=FakeUser())),
    )
    values.update(overrides)
    return SimpleNamespace(**values)


class VirtualCardTests(SimpleTestCase):
    def render(self, **overrides):
        return render_to_string("partials/virtual_card.html", {"req": fake_card(**overrides)})

    def test_only_the_last_four_digits_are_shown(self):
        html = self.render()
        self.assertIn("4243", html)
        self.assertNotIn("1234 4321", html)
        self.assertNotIn("1324", html)

    def test_holder_name_and_card_type_are_shown(self):
        html = self.render()
        self.assertIn("CUSTOMER_1", html)
        self.assertIn("DEBIT", html)

    def test_dashes_in_a_stored_mask_still_give_last_four(self):
        html = self.render(masked_card_number="XXXX-XXXX-XXXX-9876")
        self.assertIn("9876", html)

    def test_customer_frozen_card_is_marked(self):
        html = self.render(freeze_state="CUSTOMER")
        self.assertIn("vcard-frozen", html)
        self.assertIn("Frozen", html)

    def test_emergency_frozen_card_is_marked(self):
        html = self.render(freeze_state="EMERGENCY")
        self.assertIn("vcard-emergency", html)

    def test_pending_card_hides_the_number(self):
        html = self.render(status="PENDING")
        self.assertIn("vcard-off", html)
        self.assertIn("Pending", html)
        self.assertNotIn("4243", html)