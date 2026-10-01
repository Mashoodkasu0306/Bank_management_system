from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse

from audit.helpers import log_action
from audit.models import AuditLog, Actions
from services.tests import make_bank_branch, make_employee


class AuditFilterTestCase(TestCase):
    def setUp(self):
        self.bank, self.branch = make_bank_branch()
        self.emp_user, self.employee = make_employee(self.branch)  # username "emp1"
        self.admin = User.objects.create_superuser(
            username="boss", password="testpass123", email="boss@test.com"
        )
        log_action(Actions.KYC_VERIFIED, actor=self.emp_user, details="ID Proof for customer_1")
        log_action(Actions.KYC_VERIFIED, actor=self.emp_user, details="ID Proof for customer_2")
        log_action(Actions.TXN_APPROVED, actor=self.emp_user, details="Deposit approved for customer_1")
        self.client = Client()
        self.client.login(username="boss", password="testpass123")

    def entries(self, **params):
        response = self.client.get(reverse("audit_log"), params)
        return list(response.context["entries"])

    def test_person_box_finds_entries_about_a_customer(self):
        found = self.entries(username="customer_1")
        self.assertEqual(len(found), 2)

    def test_person_box_finds_entries_by_the_staff_member(self):
        found = self.entries(username="emp1")
        self.assertEqual(len(found), 3)

    def test_action_alone_works(self):
        found = self.entries(action="KYC_VERIFIED")
        self.assertEqual(len(found), 2)

    def test_both_filters_together_narrow_the_result(self):
        found = self.entries(action="KYC_VERIFIED", username="customer_1")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].action, "KYC_VERIFIED")
        self.assertIn("customer_1", found[0].details)

    def test_both_filters_together_can_give_no_match(self):
        found = self.entries(action="TXN_APPROVED", username="customer_2")
        self.assertEqual(len(found), 0)

    def test_both_empty_shows_everything(self):
        found = self.entries()
        self.assertEqual(len(found), AuditLog.objects.count())