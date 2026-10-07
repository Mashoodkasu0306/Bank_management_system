from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from audit.models import Actions, AuditLog
from notifications.helpers import notify_staff
from notifications.models import Notification
from services.tests import make_bank_branch, make_customer, make_employee
from users.models import Employee

PASSWORD = "testpass123"


class EmployeeDepartmentsPageTests(TestCase):
    def setUp(self):
        _, self.branch = make_bank_branch()
        self.emp_user, self.employee = make_employee(
            self.branch, username="emp_a", department="TRANSACTIONS"
        )
        self.other_user, self.other = make_employee(self.branch, username="emp_b", department="")
        make_customer(username="cust_x")
        User.objects.create_superuser("boss", "boss@test.com", PASSWORD)
        self.url = reverse("employee_departments")

    def login(self, username):
        self.client.logout()
        self.client.login(username=username, password=PASSWORD)

    def change(self, employee_id, department):
        return self.client.post(self.url, {"employee": employee_id, "department": department})

    def dept(self, employee=None):
        employee = employee or self.employee
        employee.refresh_from_db()
        return employee.department

    def changes(self):
        return AuditLog.objects.filter(action=Actions.EMPLOYEE_DEPARTMENT_CHANGED)

    def recipients(self):
        return set(Notification.objects.values_list("recipient__username", flat=True))

    # ---- who may use the page ----
    def test_anonymous_user_is_sent_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_customer_cannot_open_the_page(self):
        self.login("cust_x")
        self.assertNotEqual(self.client.get(self.url).status_code, 200)

    def test_employee_cannot_open_the_page(self):
        self.login("emp_a")
        self.assertNotEqual(self.client.get(self.url).status_code, 200)

    def test_employee_cannot_change_their_own_department(self):
        self.login("emp_a")
        self.change(self.employee.id, "SUPPORT")
        self.assertEqual(self.dept(), "TRANSACTIONS")
        self.assertEqual(self.changes().count(), 0)

    def test_customer_cannot_change_a_department(self):
        self.login("cust_x")
        self.change(self.employee.id, "SUPPORT")
        self.assertEqual(self.dept(), "TRANSACTIONS")
        self.assertEqual(self.changes().count(), 0)

    # ---- what the admin sees ----
    def test_admin_sees_every_employee_and_the_choices(self):
        self.login("boss")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "emp_a")
        self.assertContains(response, "emp_b")
        self.assertContains(response, "Customer Support")

    # ---- changing a department ----
    def test_admin_change_is_saved(self):
        self.login("boss")
        response = self.change(self.employee.id, "SUPPORT")
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.assertEqual(self.dept(), "SUPPORT")

    def test_change_is_audited_with_old_and_new_department(self):
        self.login("boss")
        self.change(self.employee.id, "SUPPORT")
        entry = self.changes().get()
        self.assertEqual(entry.actor_username, "boss")
        self.assertEqual(entry.target_type, "EMPLOYEE")
        self.assertEqual(entry.target_id, self.employee.id)
        self.assertEqual(entry.details, "emp_a: Transactions -> Customer Support")

    def test_admin_can_remove_a_department(self):
        self.login("boss")
        self.change(self.employee.id, "")
        self.assertEqual(self.dept(), "")
        self.assertEqual(self.changes().get().details, "emp_a: Transactions -> No department")

    def test_same_department_changes_nothing_and_is_not_audited(self):
        self.login("boss")
        self.change(self.employee.id, "TRANSACTIONS")
        self.assertEqual(self.dept(), "TRANSACTIONS")
        self.assertEqual(self.changes().count(), 0)

    def test_invalid_department_is_refused(self):
        self.login("boss")
        self.change(self.employee.id, "PIRATES")
        self.assertEqual(self.dept(), "TRANSACTIONS")
        self.assertEqual(self.changes().count(), 0)

    def test_unknown_or_bad_employee_id_is_handled(self):
        self.login("boss")
        for bad_id in ("99999", "abc", ""):
            with self.subTest(employee=bad_id):
                response = self.change(bad_id, "KYC")
                self.assertEqual(response.status_code, 302)
        self.assertEqual(self.changes().count(), 0)

    def test_every_department_choice_can_be_saved(self):
        self.login("boss")
        for value, _label in Employee.DEPARTMENT_CHOICES:
            with self.subTest(department=value):
                self.change(self.employee.id, value)
                self.assertEqual(self.dept(), value)

    # ---- the change really moves notifications ----
    def test_after_a_change_notifications_follow_the_new_department(self):
        self.login("boss")
        self.change(self.employee.id, "SUPPORT")
        notify_staff("STAFF_REQUEST", "T", "M", department="SUPPORT")
        self.assertIn("emp_a", self.recipients())
        Notification.objects.all().delete()
        notify_staff("TRANSACTION", "T", "M")
        self.assertNotIn("emp_a", self.recipients())

    def test_employee_with_no_department_receives_after_being_assigned(self):
        notify_staff("KYC", "T", "M")
        self.assertNotIn("emp_b", self.recipients())
        Notification.objects.all().delete()
        self.login("boss")
        self.change(self.other.id, "KYC")
        notify_staff("KYC", "T", "M")
        self.assertIn("emp_b", self.recipients())