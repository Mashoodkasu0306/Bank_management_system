from datetime import timedelta

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditLog, Actions
from loans.tests import make_account, make_loan
from notifications.models import Notification
from services.tests import make_bank_branch, make_customer, make_employee


class Base(TestCase):
    def setUp(self):
        self.bank, self.branch = make_bank_branch()
        self.cust_user, self.customer = make_customer(username="alina")
        self.emp_user, self.employee = make_employee(self.branch)
        self.account = make_account(self.branch, self.customer)
        self.client = Client()
        self.client.login(username="emp1", password="testpass123")

    def entries(self, action):
        return AuditLog.objects.filter(action=action)


# ============================================================================
# LOANS
# ============================================================================

class LoanAuditTestCase(Base):
    def pending_loan(self):
        return make_loan(self.account, self.customer, status="PENDING", approved_date=None)

    def test_approving_a_loan_is_logged(self):
        loan = self.pending_loan()
        self.client.post(reverse("approve_loan", args=[loan.id]), {
            "action": "approve", "interest_rate": "12",
        })
        loan.refresh_from_db()
        self.assertEqual(loan.status, "APPROVED")
        entry = self.entries(Actions.LOAN_APPROVED).get()
        self.assertEqual(entry.actor, self.emp_user)
        self.assertEqual(entry.target_type, "LOAN")
        self.assertEqual(entry.target_id, loan.id)
        self.assertIn("alina", entry.details)
        self.assertIn("12", entry.details)

    def test_rejecting_a_loan_is_logged_with_the_reason(self):
        loan = self.pending_loan()
        self.client.post(reverse("approve_loan", args=[loan.id]), {
            "action": "reject", "remarks": "Balance too low",
        })
        loan.refresh_from_db()
        self.assertEqual(loan.status, "REJECTED")
        entry = self.entries(Actions.LOAN_REJECTED).get()
        self.assertEqual(entry.target_id, loan.id)
        self.assertIn("Balance too low", entry.details)

    def test_a_customer_cannot_approve_so_nothing_is_logged(self):
        loan = self.pending_loan()
        self.client.logout()
        self.client.login(username="alina", password="testpass123")
        self.client.post(reverse("approve_loan", args=[loan.id]), {
            "action": "approve", "interest_rate": "12",
        })
        loan.refresh_from_db()
        self.assertEqual(loan.status, "PENDING")
        self.assertEqual(self.entries(Actions.LOAN_APPROVED).count(), 0)

    def test_approving_a_foreclosure_is_logged_and_the_customer_is_told(self):
        loan = make_loan(self.account, self.customer, foreclosure_status="REQUESTED")
        self.client.post(reverse("process_foreclosure", args=[loan.id]), {"action": "approve"})
        loan.refresh_from_db()
        self.assertEqual(loan.status, "CLOSED")
        entry = self.entries(Actions.FORECLOSURE_APPROVED).get()
        self.assertEqual(entry.target_id, loan.id)
        self.assertEqual(
            Notification.objects.filter(
                recipient=self.cust_user, title="Foreclosure approved"
            ).count(), 1
        )

    def test_rejecting_a_foreclosure_is_logged_and_the_customer_is_told(self):
        loan = make_loan(self.account, self.customer, foreclosure_status="REQUESTED")
        self.client.post(reverse("process_foreclosure", args=[loan.id]), {"action": "reject"})
        loan.refresh_from_db()
        self.assertEqual(loan.foreclosure_status, "REJECTED")
        entry = self.entries(Actions.FORECLOSURE_REJECTED).get()
        self.assertEqual(entry.target_id, loan.id)
        self.assertEqual(
            Notification.objects.filter(
                recipient=self.cust_user, title="Foreclosure request rejected"
            ).count(), 1
        )

    def test_renewing_a_defaulted_loan_is_logged(self):
        loan = make_loan(
            self.account, self.customer, status="DEFAULTED", tenure_months=6,
            approved_date=timezone.localtime() - timedelta(days=400),
        )
        self.client.post(reverse("renew_loan", args=[loan.id]), {"tenure_months": "6"})
        loan.refresh_from_db()
        self.assertEqual(loan.status, "RENEWED")
        entry = self.entries(Actions.LOAN_RENEWED).get()
        self.assertEqual(entry.target_id, loan.id)
        self.assertIn("alina", entry.details)


# ============================================================================
# CUSTOMERS
# ============================================================================

class CustomerAuditTestCase(Base):
    def test_registering_a_customer_is_logged(self):
        self.client.post(reverse("register_customer"), {
            "username": "newcust", "password": "testpass123",
            "customer_type": "INDIVIDUAL", "dob": "1995-05-05",
            "gender": "MALE", "address": "1 New Street",
        })
        entry = self.entries(Actions.CUSTOMER_REGISTERED).get()
        self.assertEqual(entry.actor, self.emp_user)
        self.assertEqual(entry.target_type, "CUSTOMER")
        self.assertIn("newcust", entry.details)

    def test_updating_a_customer_is_logged(self):
        self.client.post(reverse("update_customer", args=[self.customer.id]), {
            "customer_type": "INDIVIDUAL", "dob": "1990-01-01", "gender": "MALE",
            "address": "New address", "kyc_status": "PENDING",
        })
        entry = self.entries(Actions.CUSTOMER_UPDATED).get()
        self.assertEqual(entry.target_id, self.customer.id)
        self.assertIn("alina", entry.details)

    def test_deactivating_a_customer_is_logged(self):
        self.client.get(reverse("deactivate_customer", args=[self.customer.id]))
        self.cust_user.refresh_from_db()
        self.assertFalse(self.cust_user.is_active)
        entry = self.entries(Actions.CUSTOMER_DEACTIVATED).get()
        self.assertEqual(entry.target_id, self.customer.id)

    def test_reactivating_a_customer_is_logged(self):
        self.cust_user.is_active = False
        self.cust_user.save()
        self.client.get(reverse("activate_customer", args=[self.customer.id]))
        self.cust_user.refresh_from_db()
        self.assertTrue(self.cust_user.is_active)
        entry = self.entries(Actions.CUSTOMER_ACTIVATED).get()
        self.assertEqual(entry.target_id, self.customer.id)