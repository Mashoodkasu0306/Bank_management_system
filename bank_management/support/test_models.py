from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from audit.models import Actions
from notifications.models import Notification
from users.models import Customer

from .models import SupportCase, SupportMessage


class SupportCaseModelTests(TestCase):
    def setUp(self):
        user = User.objects.create_user("case_customer", password="pass12345")
        self.customer = Customer.objects.create(
            user=user, customer_type="INDIVIDUAL", dob=date(1990, 1, 1),
            gender="MALE", address="Test street", kyc_status="VERIFIED",
        )

    def make_case(self, case_type=SupportCase.DISPUTE):
        return SupportCase.objects.create(
            customer=self.customer, case_type=case_type, category="OTHER",
            subject="Test case", description="Something went wrong",
        )

    def test_new_case_is_open_and_not_overdue(self):
        case = self.make_case()
        self.assertEqual(case.status, SupportCase.OPEN)
        self.assertTrue(case.is_open)
        self.assertFalse(case.is_overdue)

    def test_dispute_deadline_is_ten_days(self):
        case = self.make_case(SupportCase.DISPUTE)
        gap = case.due_at - timezone.now()
        self.assertLess(abs(gap - timedelta(days=10)), timedelta(minutes=1))

    def test_complaint_deadline_is_seven_days(self):
        case = self.make_case(SupportCase.COMPLAINT)
        gap = case.due_at - timezone.now()
        self.assertLess(abs(gap - timedelta(days=7)), timedelta(minutes=1))

    def test_reference_number(self):
        case = self.make_case()
        self.assertEqual(case.reference, f"CASE-{case.pk:06d}")

    def test_open_case_past_deadline_is_overdue(self):
        case = self.make_case()
        case.due_at = timezone.now() - timedelta(hours=1)
        case.save()
        self.assertTrue(case.is_overdue)

    def test_decided_case_is_never_overdue(self):
        case = self.make_case()
        case.due_at = timezone.now() - timedelta(hours=1)
        case.status = SupportCase.REJECTED
        case.save()
        self.assertFalse(case.is_open)
        self.assertFalse(case.is_overdue)

    def test_messages_come_back_in_order(self):
        case = self.make_case()
        SupportMessage.objects.create(case=case, body="first")
        SupportMessage.objects.create(case=case, body="second", from_staff=True)
        bodies = [m.body for m in case.messages.all()]
        self.assertEqual(bodies, ["first", "second"])

    def test_audit_actions_are_registered(self):
        for name in ("CASE_OPENED", "CASE_REPLIED", "CASE_PICKED_UP",
                     "CASE_ACCEPTED", "CASE_REJECTED"):
            self.assertIn(getattr(Actions, name), Actions.ALL)

    def test_notification_category_exists(self):
        self.assertIn("SUPPORT_CASE", dict(Notification.CATEGORY_CHOICES))
        self.assertEqual(Notification.CATEGORY_GROUP["SUPPORT_CASE"], "SUPPORT")