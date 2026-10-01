from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import Account
from bank.models import Branch
from users.models import Customer
from services.tests import make_bank_branch, make_employee


class RegisterCustomerTestCase(TestCase):
    def setUp(self):
        self.bank, self.branch = make_bank_branch()
        self.emp_user, self.employee = make_employee(self.branch)
        self.client = Client()

    def form(self, username="newcust", **extra):
        data = {
            "username": username, "password": "testpass123",
            "customer_type": "INDIVIDUAL", "dob": "1995-05-05",
            "gender": "MALE", "address": "1 New Street",
        }
        data.update(extra)
        return data

    def login_employee(self):
        self.client.login(username="emp1", password="testpass123")

    def login_admin(self):
        User.objects.create_superuser(username="boss", password="testpass123", email="b@test.com")
        self.client.login(username="boss", password="testpass123")

    def test_employee_registration_opens_a_savings_account_at_their_branch(self):
        self.login_employee()
        self.client.post(reverse("register_customer"), self.form())
        customer = Customer.objects.get(user__username="newcust")
        account = Account.objects.get(customer=customer)
        self.assertEqual(account.account_type, "SAVINGS")
        self.assertEqual(account.status, "ACTIVE")
        self.assertEqual(account.branch, self.branch)
        self.assertEqual(account.balance, 0)

    def test_account_type_current_is_respected(self):
        self.login_employee()
        self.client.post(reverse("register_customer"), self.form(account_type="CURRENT"))
        self.assertEqual(Account.objects.get().account_type, "CURRENT")

    def test_loan_account_type_is_not_allowed_and_falls_back_to_savings(self):
        self.login_employee()
        self.client.post(reverse("register_customer"), self.form(account_type="LOAN"))
        self.assertEqual(Account.objects.get().account_type, "SAVINGS")

    def test_admin_without_a_branch_still_registers_the_customer_but_opens_no_account(self):
        self.login_admin()
        self.client.post(reverse("register_customer"), self.form())
        self.assertTrue(Customer.objects.filter(user__username="newcust").exists())
        self.assertEqual(Account.objects.count(), 0)

    def test_admin_can_choose_a_branch(self):
        branch2 = Branch.objects.create(
            bank=self.bank, name="Second Branch", branch_code="BR02",
            address="456 Test St", city="Test City", state="Test State",
            ifsc_code="TB0100002",
        )
        self.login_admin()
        self.client.post(reverse("register_customer"), self.form(branch=str(branch2.id)))
        self.assertEqual(Account.objects.get().branch, branch2)

    def test_duplicate_username_creates_nothing(self):
        self.login_employee()
        self.client.post(reverse("register_customer"), self.form(username="emp1"))
        self.assertEqual(User.objects.filter(username="emp1").count(), 1)
        self.assertEqual(Customer.objects.count(), 0)
        self.assertEqual(Account.objects.count(), 0)