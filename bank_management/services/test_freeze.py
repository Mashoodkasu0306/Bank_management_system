from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import Account
from audit.models import Actions
from services.freeze import (
    customer_has_active_freeze, emergency_freeze, lift_emergency_freeze,
)
from services.models import ATMCardRequest, EmergencyFreeze
from services.tests import make_bank_branch, make_customer, make_employee


class FreezeTestBase(TestCase):
    def setUp(self):
        self.bank, self.branch = make_bank_branch()
        self.user, self.customer = make_customer(username="cust1")
        self.other_user, self.other = make_customer(username="cust2")
        self.staff_user, self.staff = make_employee(self.branch, department="SUPPORT")
        self.account = self.make_account(self.customer)
        self.other_account = self.make_account(self.other)

    def make_account(self, customer):
        return Account.objects.create(
            customer=customer, branch=self.branch, account_type="SAVINGS",
            status="ACTIVE", balance=Decimal("1000.00"), daily_limit=Decimal("50000.00"),
        )

    def make_card(self, account, status="APPROVED", freeze_state=""):
        return ATMCardRequest.objects.create(
            account=account, status=status, delivery_address="Test Address",
            masked_card_number="XXXX-XXXX-XXXX-1234", freeze_state=freeze_state,
        )

    def state(self, card):
        card.refresh_from_db()
        return card.freeze_state


class EmergencyFreezeTestCase(FreezeTestBase):
    def test_freezes_approved_and_delivered_cards_only(self):
        approved = self.make_card(self.account, "APPROVED")
        delivered = self.make_card(self.account, "DELIVERED")
        pending = self.make_card(self.account, "PENDING")
        rejected = self.make_card(self.account, "REJECTED")
        freeze, count = emergency_freeze(self.customer)
        self.assertIsNotNone(freeze)
        self.assertEqual(count, 2)
        self.assertEqual(self.state(approved), "EMERGENCY")
        self.assertEqual(self.state(delivered), "EMERGENCY")
        self.assertEqual(self.state(pending), "")
        self.assertEqual(self.state(rejected), "")

    def test_works_even_with_no_cards(self):
        freeze, count = emergency_freeze(self.customer)
        self.assertIsNotNone(freeze)
        self.assertEqual(count, 0)
        self.assertTrue(customer_has_active_freeze(self.customer))

    def test_card_the_customer_froze_stays_a_customer_freeze(self):
        mine = self.make_card(self.account, freeze_state="CUSTOMER")
        emergency_freeze(self.customer)
        self.assertEqual(self.state(mine), "CUSTOMER")

    def test_second_emergency_freeze_is_refused(self):
        emergency_freeze(self.customer)
        freeze, count = emergency_freeze(self.customer)
        self.assertIsNone(freeze)
        self.assertEqual(count, 0)
        self.assertEqual(EmergencyFreeze.objects.filter(customer=self.customer).count(), 1)

    def test_other_customers_are_not_affected(self):
        theirs = self.make_card(self.other_account)
        emergency_freeze(self.customer)
        self.assertEqual(self.state(theirs), "")
        self.assertFalse(customer_has_active_freeze(self.other))

    def test_database_refuses_two_active_freezes(self):
        EmergencyFreeze.objects.create(customer=self.customer)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                EmergencyFreeze.objects.create(customer=self.customer)


class LiftFreezeTestCase(FreezeTestBase):
    def test_lifting_unfreezes_emergency_cards_but_not_customer_frozen_ones(self):
        emergency_card = self.make_card(self.account)
        mine = self.make_card(self.account, freeze_state="CUSTOMER")
        freeze, _ = emergency_freeze(self.customer)
        self.assertTrue(lift_emergency_freeze(freeze, self.staff_user, "Confirmed by phone"))
        self.assertEqual(self.state(emergency_card), "")
        self.assertEqual(self.state(mine), "CUSTOMER")
        self.assertFalse(customer_has_active_freeze(self.customer))

    def test_lift_records_who_and_why(self):
        freeze, _ = emergency_freeze(self.customer)
        lift_emergency_freeze(freeze, self.staff_user, "Confirmed by phone")
        freeze.refresh_from_db()
        self.assertEqual(freeze.lifted_by, self.staff_user)
        self.assertEqual(freeze.lift_note, "Confirmed by phone")
        self.assertIsNotNone(freeze.lifted_at)

    def test_lifting_twice_returns_false(self):
        freeze, _ = emergency_freeze(self.customer)
        self.assertTrue(lift_emergency_freeze(freeze, self.staff_user, "ok"))
        self.assertFalse(lift_emergency_freeze(freeze, self.staff_user, "again"))

    def test_customer_can_freeze_again_after_a_lift(self):
        freeze, _ = emergency_freeze(self.customer)
        lift_emergency_freeze(freeze, self.staff_user, "ok")
        again, _ = emergency_freeze(self.customer)
        self.assertIsNotNone(again)


class AuditActionsTestCase(TestCase):
    def test_new_actions_are_listed(self):
        for name in ("EMPLOYEE_DEPARTMENT_CHANGED", "CARD_FROZEN", "CARD_UNFROZEN",
                     "CARD_LIMIT_SET", "EMERGENCY_FREEZE", "EMERGENCY_FREEZE_LIFTED"):
            self.assertIn(getattr(Actions, name), Actions.ALL)
