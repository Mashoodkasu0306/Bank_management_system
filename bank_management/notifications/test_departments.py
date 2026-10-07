from django.contrib.auth.models import User
from django.test import TestCase

from notifications.helpers import DEPARTMENT_FOR_CATEGORY, notify_staff
from notifications.models import Notification
from services.tests import make_bank_branch, make_customer, make_employee

DEPARTMENTS = (
    "TRANSACTIONS", "LOANS", "KYC", "ACCOUNT_OPENING", "CARDS_SERVICES", "SUPPORT",
)

# Which employee should receive each routed category.
EXPECTED = {
    "TRANSACTION": "emp_transactions",
    "LOAN": "emp_loans",
    "KYC": "emp_kyc",
    "ATM_CARD": "emp_cards_services",
    "CHEQUE_BOOK": "emp_cards_services",
}


class DepartmentRoutingTests(TestCase):
    def setUp(self):
        _, self.branch = make_bank_branch()
        for dept in DEPARTMENTS:
            make_employee(self.branch, username=f"emp_{dept.lower()}", department=dept)
        make_employee(self.branch, username="emp_none", department="")
        make_customer(username="cust_x")
        User.objects.create_superuser("boss", "boss@test.com", "testpass123")

    def send(self, category, **kwargs):
        notify_staff(category, "Title", "Message", **kwargs)

    def recipients(self):
        return set(Notification.objects.values_list("recipient__username", flat=True))

    def test_each_category_reaches_only_its_department_and_admin(self):
        for category, username in EXPECTED.items():
            with self.subTest(category=category):
                Notification.objects.all().delete()
                self.send(category)
                self.assertEqual(self.recipients(), {username, "boss"})

    def test_mapping_covers_every_routed_category(self):
        # SUPPORT_CASE is for customers and STAFF_REQUEST names its department by hand.
        # Any other new category must be added to DEPARTMENT_FOR_CATEGORY.
        categories = {code for code, _ in Notification.CATEGORY_CHOICES}
        self.assertEqual(
            set(DEPARTMENT_FOR_CATEGORY), categories - {"STAFF_REQUEST", "SUPPORT_CASE"}
        )

    def test_staff_request_without_department_goes_to_admins_only(self):
        self.send("STAFF_REQUEST")
        self.assertEqual(self.recipients(), {"boss"})

    def test_staff_request_with_department_goes_to_that_department(self):
        self.send("STAFF_REQUEST", department="SUPPORT")
        self.assertEqual(self.recipients(), {"emp_support", "boss"})

    def test_named_department_overrides_the_category(self):
        self.send("KYC", department="LOANS")
        self.assertEqual(self.recipients(), {"emp_loans", "boss"})

    def test_employee_without_department_gets_nothing(self):
        for category in list(EXPECTED) + ["STAFF_REQUEST"]:
            self.send(category)
        self.assertNotIn("emp_none", self.recipients())

    def test_customers_never_get_staff_notifications(self):
        for category in list(EXPECTED) + ["STAFF_REQUEST"]:
            self.send(category)
        self.assertNotIn("cust_x", self.recipients())

    def test_everyone_in_the_department_gets_it(self):
        make_employee(self.branch, username="emp_kyc_two", department="KYC")
        self.send("KYC")
        self.assertEqual(self.recipients(), {"emp_kyc", "emp_kyc_two", "boss"})

    def test_every_admin_gets_it(self):
        User.objects.create_superuser("boss_two", "boss2@test.com", "testpass123")
        self.send("LOAN")
        self.assertEqual(self.recipients(), {"emp_loans", "boss", "boss_two"})

    def test_department_with_nobody_goes_to_admins_only(self):
        from users.models import Employee
        Employee.objects.filter(department="LOANS").delete()
        self.send("LOAN")
        self.assertEqual(self.recipients(), {"boss"})

    def test_moving_an_employee_changes_who_is_notified(self):
        from users.models import Employee
        Employee.objects.filter(user__username="emp_kyc").update(department="LOANS")
        self.send("KYC")
        self.assertEqual(self.recipients(), {"boss"})
        Notification.objects.all().delete()
        self.send("LOAN")
        self.assertEqual(self.recipients(), {"emp_loans", "emp_kyc", "boss"})

    def test_notification_details_are_stored(self):
        self.send("KYC", link="/x/", related_type="KYC", related_id=7)
        note = Notification.objects.get(recipient__username="boss")
        self.assertEqual(note.link, "/x/")
        self.assertEqual(note.related_type, "KYC")
        self.assertEqual(note.related_id, 7)
        self.assertEqual(note.priority, "MEDIUM")
        Notification.objects.all().delete()
        self.send("TRANSACTION")
        self.assertEqual(Notification.objects.first().priority, "HIGH")
        Notification.objects.all().delete()
        self.send("LOAN", priority="CRITICAL")
        self.assertEqual(set(Notification.objects.values_list("priority", flat=True)), {"CRITICAL"})