import re
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import Account
from audit.models import AuditLog, Actions
from services.models import KYCVerification, KYCDocument, ATMCardRequest, ChequebookRequest
from services.tests import make_bank_branch, make_customer, make_employee
from transactions.models import Transaction


class AuditHookBase(TestCase):
    def setUp(self):
        self.bank, self.branch = make_bank_branch()
        self.cust_user, self.customer = make_customer(username="alina")
        self.emp_user, self.employee = make_employee(self.branch)
        self.account = Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="SAVINGS",
            status="ACTIVE", balance=Decimal("5000.00"),
        )
        self.client = Client()
        self.client.login(username="emp1", password="testpass123")

    def entries(self, action):
        return AuditLog.objects.filter(action=action)


# ============================================================================
# KYC
# ============================================================================

class KYCAuditTestCase(AuditHookBase):
    def make_doc(self):
        kyc = KYCVerification.objects.create(customer=self.customer)
        return KYCDocument.objects.create(
            kyc_verification=kyc, document_type="ID_PROOF",
            file=SimpleUploadedFile("id.pdf", b"dummy", content_type="application/pdf"),
        )

    def test_verifying_a_document_is_logged(self):
        doc = self.make_doc()
        self.client.post(reverse("verify_kyc_document", args=[doc.id]), {
            "verification_status": "VERIFIED", "reviewer_notes": "Looks good",
        })
        entry = self.entries(Actions.KYC_VERIFIED).get()
        self.assertEqual(entry.actor, self.emp_user)
        self.assertEqual(entry.target_type, "KYC_DOCUMENT")
        self.assertEqual(entry.target_id, doc.id)
        self.assertIn("alina", entry.details)

    def test_rejecting_a_document_is_logged_with_the_reason(self):
        doc = self.make_doc()
        self.client.post(reverse("verify_kyc_document", args=[doc.id]), {
            "verification_status": "REJECTED", "rejection_reason": "Photo is blurry",
        })
        entry = self.entries(Actions.KYC_REJECTED).get()
        self.assertEqual(entry.target_id, doc.id)
        self.assertIn("Photo is blurry", entry.details)

    def test_a_rejection_without_a_reason_is_not_logged(self):
        doc = self.make_doc()
        self.client.post(reverse("verify_kyc_document", args=[doc.id]), {
            "verification_status": "REJECTED", "rejection_reason": "",
        })
        self.assertEqual(self.entries(Actions.KYC_REJECTED).count(), 0)
        self.assertEqual(self.entries(Actions.KYC_VERIFIED).count(), 0)


# ============================================================================
# ATM CARDS
# ============================================================================

class ATMAuditTestCase(AuditHookBase):
    def make_request(self):
        return ATMCardRequest.objects.create(
            account=self.account, status="PENDING", delivery_address="Test Address"
        )

    def test_approval_is_logged_without_any_card_details(self):
        req = self.make_request()
        self.client.post(reverse("approve_atm_card_request", args=[req.id]), {
            "approval_status": "APPROVED",
        })
        entry = self.entries(Actions.ATM_APPROVED).get()
        self.assertEqual(entry.target_type, "ATM_CARD_REQUEST")
        self.assertEqual(entry.target_id, req.id)
        self.assertIn("alina", entry.details)
        self.assertNotIn("XXXX", entry.details)
        self.assertIsNone(re.search(r"\d{12,}", entry.details))

    def test_rejection_is_logged_with_the_reason(self):
        req = self.make_request()
        self.client.post(reverse("approve_atm_card_request", args=[req.id]), {
            "approval_status": "REJECTED", "rejection_reason": "Incomplete address",
        })
        entry = self.entries(Actions.ATM_REJECTED).get()
        self.assertEqual(entry.target_id, req.id)
        self.assertIn("Incomplete address", entry.details)


# ============================================================================
# CHEQUE BOOKS
# ============================================================================

class ChequeAuditTestCase(AuditHookBase):
    def make_request(self):
        return ChequebookRequest.objects.create(
            account=self.account, leaf_count=50, status="PENDING",
            delivery_address="Test Address",
        )

    def test_approval_is_logged_with_the_fee(self):
        req = self.make_request()
        self.client.post(reverse("approve_cheque_book_request", args=[req.id]), {
            "approval_status": "APPROVED", "cheque_book_fee": "50.00",
        })
        entry = self.entries(Actions.CHEQUE_APPROVED).get()
        self.assertEqual(entry.target_type, "CHEQUE_BOOK_REQUEST")
        self.assertEqual(entry.target_id, req.id)
        self.assertIn("50.00", entry.details)

    def test_rejection_is_logged_with_the_reason(self):
        req = self.make_request()
        self.client.post(reverse("approve_cheque_book_request", args=[req.id]), {
            "approval_status": "REJECTED", "cheque_book_fee": "0.00",
            "rejection_reason": "Account is too new",
        })
        entry = self.entries(Actions.CHEQUE_REJECTED).get()
        self.assertEqual(entry.target_id, req.id)
        self.assertIn("Account is too new", entry.details)


# ============================================================================
# PENDING TRANSACTIONS
# ============================================================================

class TransactionAuditTestCase(AuditHookBase):
    def make_pending(self, txn_type, amount, **accounts):
        return Transaction.objects.create(
            transaction_type=txn_type, amount=Decimal(amount), status="PENDING",
            performed_by=self.emp_user,
            remarks="Exceeds daily limit; awaiting approval", **accounts,
        )

    def act(self, txn, action):
        return self.client.post(
            reverse("approve_transaction", args=[txn.id]), {"action": action}
        )

    def test_approval_is_logged(self):
        txn = self.make_pending("DEPOSIT", "1000.00", to_account=self.account)
        self.act(txn, "approve")
        entry = self.entries(Actions.TXN_APPROVED).get()
        self.assertEqual(entry.actor, self.emp_user)
        self.assertEqual(entry.target_type, "TRANSACTION")
        self.assertEqual(entry.target_id, txn.id)

    def test_rejection_is_logged(self):
        txn = self.make_pending("DEPOSIT", "1000.00", to_account=self.account)
        self.act(txn, "reject")
        entry = self.entries(Actions.TXN_REJECTED).get()
        self.assertEqual(entry.target_id, txn.id)

    def test_an_approval_that_fails_is_logged_as_a_rejection(self):
        txn = self.make_pending("WITHDRAW", "90000.00", from_account=self.account)
        self.act(txn, "approve")
        self.assertEqual(self.entries(Actions.TXN_APPROVED).count(), 0)
        self.assertEqual(self.entries(Actions.TXN_REJECTED).count(), 1)

    def test_a_customer_cannot_approve_so_nothing_is_logged(self):
        txn = self.make_pending("DEPOSIT", "1000.00", to_account=self.account)
        self.client.logout()
        self.client.login(username="alina", password="testpass123")
        self.act(txn, "approve")
        self.assertEqual(self.entries(Actions.TXN_APPROVED).count(), 0)
        self.assertEqual(self.entries(Actions.TXN_REJECTED).count(), 0)