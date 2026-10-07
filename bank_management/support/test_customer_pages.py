from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from audit.models import Actions, AuditLog
from notifications.models import Notification
from users.models import Customer, Employee

from .models import SupportCase, SupportMessage
from .services import MAX_OPEN_CASES


def make_customer(username):
    user = User.objects.create_user(username, password="pass12345")
    return Customer.objects.create(
        user=user, customer_type="INDIVIDUAL", dob=date(1990, 1, 1),
        gender="MALE", address="Test street", kyc_status="VERIFIED",
    )


def make_employee(username, department):
    user = User.objects.create_user(username, password="pass12345")
    Employee.objects.create(
        user=user, role="clerk", department=department,
        salary=1000, date_of_joining=date(2024, 1, 1),
    )
    return user


COMPLAINT = {
    "case_type": "COMPLAINT", "category": "SERVICE",
    "subject": "Slow branch", "description": "I waited two hours.",
}


class CustomerCasePagesTests(TestCase):
    def setUp(self):
        self.customer = make_customer("cust_one")
        self.other = make_customer("cust_two")
        self.support_user = make_employee("support_emp", "SUPPORT")
        self.kyc_user = make_employee("kyc_emp", "KYC")
        self.client.login(username="cust_one", password="pass12345")

    def make_case(self, customer=None, **extra):
        return SupportCase.objects.create(
            customer=customer or self.customer, case_type="COMPLAINT",
            category="OTHER", **{"subject": "Existing", "description": "text", **extra},
        )

    def test_anonymous_user_is_sent_to_login(self):
        self.client.logout()
        response = self.client.get(reverse("support_my_cases"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_staff_cannot_use_customer_pages(self):
        self.client.login(username="support_emp", password="pass12345")
        response = self.client.get(reverse("support_my_cases"))
        self.assertRedirects(response, reverse("employee_dashboard"), fetch_redirect_response=False)

    def test_complaint_is_created(self):
        response = self.client.post(reverse("support_raise_case"), COMPLAINT)
        case = SupportCase.objects.get()
        self.assertRedirects(response, reverse("support_case_detail", args=[case.id]))
        self.assertEqual(case.customer, self.customer)
        self.assertEqual(case.case_type, SupportCase.COMPLAINT)
        self.assertEqual(case.status, SupportCase.OPEN)

    def test_opening_a_case_is_audited(self):
        self.client.post(reverse("support_raise_case"), COMPLAINT)
        self.assertEqual(AuditLog.objects.filter(action=Actions.CASE_OPENED).count(), 1)

    def test_customer_gets_a_confirmation(self):
        self.client.post(reverse("support_raise_case"), COMPLAINT)
        mine = Notification.objects.filter(recipient=self.customer.user, category="SUPPORT_CASE")
        self.assertEqual(mine.count(), 1)

    def test_only_support_department_is_alerted(self):
        self.client.post(reverse("support_raise_case"), COMPLAINT)
        alerts = Notification.objects.filter(category="STAFF_REQUEST", related_type="SUPPORT_CASE")
        self.assertEqual(alerts.filter(recipient=self.support_user).count(), 1)
        self.assertEqual(alerts.filter(recipient=self.kyc_user).count(), 0)

    def test_dispute_without_transaction_is_rejected(self):
        data = dict(COMPLAINT, case_type="DISPUTE")
        response = self.client.post(reverse("support_raise_case"), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(SupportCase.objects.count(), 0)

    def test_open_case_limit(self):
        for _ in range(MAX_OPEN_CASES):
            self.make_case()
        self.client.post(reverse("support_raise_case"), COMPLAINT)
        self.assertEqual(SupportCase.objects.count(), MAX_OPEN_CASES)

    def test_my_cases_shows_only_my_cases(self):
        self.make_case(subject="Mine only")
        self.make_case(customer=self.other, subject="Not mine")
        response = self.client.get(reverse("support_my_cases"))
        self.assertContains(response, "Mine only")
        self.assertNotContains(response, "Not mine")

    def test_other_customers_case_is_not_found(self):
        theirs = self.make_case(customer=self.other)
        response = self.client.get(reverse("support_case_detail", args=[theirs.id]))
        self.assertEqual(response.status_code, 404)

    def test_reply_is_saved_audited_and_staff_alerted(self):
        case = self.make_case()
        self.client.post(reverse("support_case_reply", args=[case.id]), {"body": "Any news?"})
        self.assertEqual(SupportMessage.objects.filter(case=case, from_staff=False).count(), 1)
        self.assertEqual(AuditLog.objects.filter(action=Actions.CASE_REPLIED).count(), 1)
        alerts = Notification.objects.filter(recipient=self.support_user, related_id=case.id)
        self.assertEqual(alerts.count(), 1)

    def test_reply_on_decided_case_is_blocked(self):
        case = self.make_case(status=SupportCase.ACCEPTED)
        self.client.post(reverse("support_case_reply", args=[case.id]), {"body": "Thanks"})
        self.assertEqual(SupportMessage.objects.filter(case=case).count(), 0)

    def test_cannot_reply_to_another_customers_case(self):
        theirs = self.make_case(customer=self.other)
        response = self.client.post(reverse("support_case_reply", args=[theirs.id]), {"body": "Hi"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(SupportMessage.objects.count(), 0)