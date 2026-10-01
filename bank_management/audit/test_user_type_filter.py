from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse

from audit.helpers import log_action
from audit.models import AuditLog, Actions
from audit.views import CUSTOMER_ACTIONS
from services.tests import make_bank_branch, make_customer, make_employee


class UserTypeFilterTestCase(TestCase):
    def setUp(self):
        self.bank, self.branch = make_bank_branch()
        self.cust_user, self.customer = make_customer(username="alina")
        self.emp_user, self.employee = make_employee(self.branch)  # username "emp1"
        self.admin = User.objects.create_superuser(
            username="boss", password="testpass123", email="boss@test.com"
        )

        log_action(Actions.KYC_VERIFIED, actor=self.emp_user, details="ID Proof for alina")
        log_action(Actions.LOGIN_SUCCESS, actor=self.cust_user)
        log_action(Actions.LOGOUT, actor=self.cust_user)
        log_action(Actions.LOGIN_FAILED, username="alina")   # wrong password, nobody signed in
        log_action(Actions.LOGIN_FAILED, username="nobody")  # a name that does not exist

        self.client = Client()
        self.client.login(username="boss", password="testpass123")  # also logs boss's own login

    def get(self, **params):
        return self.client.get(reverse("audit_log"), params)

    def entries(self, **params):
        return list(self.get(**params).context["entries"])

    def test_customer_type_shows_only_that_customers_entries(self):
        found = self.entries(user_type="CUSTOMER")
        self.assertEqual(len(found), 3)
        self.assertEqual({e.actor_username for e in found}, {"alina"})

    def test_employee_type_shows_staff_and_admin_entries_only(self):
        found = self.entries(user_type="EMPLOYEE")
        self.assertEqual({e.actor_username for e in found}, {"emp1", "boss"})

    def test_a_failed_login_for_an_unknown_name_belongs_to_neither_group(self):
        for kind in ("CUSTOMER", "EMPLOYEE"):
            names = {e.actor_username for e in self.entries(user_type=kind)}
            self.assertNotIn("nobody", names)
        everyone = {e.actor_username for e in self.entries()}
        self.assertIn("nobody", everyone)

    def test_action_list_for_customer_is_the_customer_actions(self):
        response = self.get(user_type="CUSTOMER")
        self.assertEqual(tuple(response.context["actions"]), CUSTOMER_ACTIONS)

    def test_action_list_for_employee_includes_staff_decisions(self):
        actions = list(self.get(user_type="EMPLOYEE").context["actions"])
        self.assertIn("KYC_VERIFIED", actions)
        self.assertIn("LOAN_APPROVED", actions)

    def test_action_list_with_no_type_has_everything(self):
        actions = list(self.get().context["actions"])
        self.assertEqual(set(actions), set(Actions.ALL))

    def test_type_and_action_work_together(self):
        found = self.entries(user_type="CUSTOMER", action="LOGOUT")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].action, "LOGOUT")

    def test_type_action_and_name_all_combine(self):
        yes = self.entries(user_type="CUSTOMER", action="LOGIN_SUCCESS", username="alina")
        no = self.entries(user_type="CUSTOMER", action="LOGIN_SUCCESS", username="zzz")
        self.assertEqual(len(yes), 1)
        self.assertEqual(len(no), 0)

    def test_an_action_that_does_not_fit_the_type_is_ignored(self):
        response = self.get(user_type="CUSTOMER", action="KYC_VERIFIED")
        self.assertEqual(response.context["selected_action"], "")
        self.assertEqual(len(list(response.context["entries"])), 3)

    def test_an_unknown_user_type_is_ignored(self):
        response = self.get(user_type="HACKER")
        self.assertEqual(response.context["selected_user_type"], "")
        self.assertEqual(len(list(response.context["entries"])), AuditLog.objects.count())