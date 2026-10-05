from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from audit.models import Actions, AuditLog
from notifications.models import Notification
from services.freeze import lift_emergency_freeze
from services.models import ATMCardRequest, ChequebookRequest, EmergencyFreeze
from services.test_freeze import FreezeTestBase
from services.tests import make_employee, make_verified_kyc
from transactions.models import Transaction


class CardControlsTestBase(FreezeTestBase):
    def setUp(self):
        super().setUp()
        make_verified_kyc(self.customer)
        self.card = self.make_card(self.account)
        self.client = Client()
        self.client.login(username="cust1", password="testpass123")

    def post_card(self, name, card, **data):
        return self.client.post(reverse(name, args=[card.id]), data)

    def audit(self, action):
        return AuditLog.objects.filter(action=action)


class CustomerCardPagesTestCase(CardControlsTestBase):
    def test_page_lists_only_real_cards(self):
        ATMCardRequest.objects.create(
            account=self.account, status="PENDING", delivery_address="x",
            masked_card_number="XXXX-XXXX-XXXX-9999",
        )
        html = self.client.get(reverse("card_controls")).content.decode()
        self.assertIn("1234", html)
        self.assertNotIn("9999", html)

    def test_staff_cannot_open_the_customer_card_page(self):
        client = Client()
        client.login(username="emp1", password="testpass123")
        self.assertEqual(client.get(reverse("card_controls")).status_code, 302)

    def test_customer_can_freeze_and_unfreeze_own_card(self):
        self.post_card("card_freeze_toggle", self.card, action="freeze")
        self.assertEqual(self.state(self.card), "CUSTOMER")
        self.assertEqual(self.audit(Actions.CARD_FROZEN).count(), 1)
        self.post_card("card_freeze_toggle", self.card, action="unfreeze")
        self.assertEqual(self.state(self.card), "")
        self.assertEqual(self.audit(Actions.CARD_UNFROZEN).count(), 1)

    def test_cannot_change_someone_elses_card(self):
        theirs = self.make_card(self.other_account)
        self.post_card("card_freeze_toggle", theirs, action="freeze")
        self.assertEqual(self.state(theirs), "")

    def test_a_card_that_is_not_approved_cannot_be_frozen(self):
        pending = self.make_card(self.account, status="PENDING")
        self.post_card("card_freeze_toggle", pending, action="freeze")
        self.assertEqual(self.state(pending), "")

    def test_changes_need_a_post_request(self):
        url = reverse("card_freeze_toggle", args=[self.card.id])
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_set_and_clear_the_limit(self):
        self.post_card("card_set_limit", self.card, limit="2500")
        self.card.refresh_from_db()
        self.assertEqual(self.card.card_daily_limit, Decimal("2500.00"))
        self.assertEqual(self.audit(Actions.CARD_LIMIT_SET).count(), 1)
        self.post_card("card_set_limit", self.card, limit="")
        self.card.refresh_from_db()
        self.assertIsNone(self.card.card_daily_limit)

    def test_bad_limits_are_refused(self):
        for bad in ("abc", "0", "-5", "NaN", "60000"):  # the account's daily limit is 50000
            self.post_card("card_set_limit", self.card, limit=bad)
            self.card.refresh_from_db()
            self.assertIsNone(self.card.card_daily_limit, bad)


class EmergencyFreezePagesTestCase(CardControlsTestBase):
    def setUp(self):
        super().setUp()
        # emp1 (from the base class) is in Customer Support.
        make_employee(self.branch, username="kycguy", department="KYC")
        User.objects.create_superuser(username="boss", password="x", email="boss@test.com")

    def press(self):
        return self.client.post(reverse("emergency_freeze_start"))

    def transfer(self):
        return self.client.post(reverse("customer_transfer"), {
            "from_account_no": self.account.account_no,
            "to_account_no": self.other_account.account_no,
            "amount": "100.00",
        })

    def test_emergency_freezes_cards_and_alerts_the_right_people(self):
        self.press()
        freeze = EmergencyFreeze.objects.get(customer=self.customer)
        self.assertEqual(self.state(self.card), "EMERGENCY")
        self.assertEqual(self.audit(Actions.EMERGENCY_FREEZE).count(), 1)
        mine = Notification.objects.filter(recipient=self.user, priority="CRITICAL")
        self.assertEqual(mine.count(), 1)
        staff = Notification.objects.filter(related_type="FREEZE", related_id=freeze.id)
        self.assertEqual(set(staff.values_list("recipient__username", flat=True)), {"emp1", "boss"})
        self.assertEqual(set(staff.values_list("priority", flat=True)), {"CRITICAL"})

    def test_pressing_twice_changes_nothing_more(self):
        self.press()
        self.press()
        self.assertEqual(EmergencyFreeze.objects.filter(customer=self.customer).count(), 1)
        self.assertEqual(self.audit(Actions.EMERGENCY_FREEZE).count(), 1)

    def test_cards_cannot_be_changed_during_an_emergency_freeze(self):
        self.press()
        self.post_card("card_freeze_toggle", self.card, action="unfreeze")
        self.assertEqual(self.state(self.card), "EMERGENCY")
        self.post_card("card_set_limit", self.card, limit="100")
        self.card.refresh_from_db()
        self.assertIsNone(self.card.card_daily_limit)

    def test_online_transfer_is_blocked_during_a_freeze(self):
        self.press()
        response = self.transfer()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Transaction.objects.filter(from_account=self.account).count(), 0)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("1000.00"))

    def test_transfer_works_again_after_staff_lift(self):
        self.press()
        freeze = EmergencyFreeze.objects.get(customer=self.customer)
        lift_emergency_freeze(freeze, self.staff_user, "Confirmed by phone")
        self.transfer()
        self.assertEqual(
            Transaction.objects.filter(from_account=self.account, status="SUCCESS").count(), 1
        )

    def test_cheque_fee_payment_is_blocked_during_a_freeze(self):
        cheque = ChequebookRequest.objects.create(
            account=self.account, status="APPROVED", leaf_count=25,
            delivery_address="Test Address", cheque_book_fee=Decimal("100.00"),
        )
        self.press()
        self.client.post(reverse("confirm_pay_cheque_book_fee", args=[cheque.id]), {
            "account": str(self.account.id), "mode_of_transaction": "NETBANKING",
        })
        cheque.refresh_from_db()
        self.account.refresh_from_db()
        self.assertFalse(cheque.fee_charged)
        self.assertEqual(self.account.balance, Decimal("1000.00"))
