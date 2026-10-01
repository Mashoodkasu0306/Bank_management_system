from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import Account
from audit.models import AuditLog, Actions
from audit.views import STAFF_ACTIONS, CUSTOMER_ACTIONS
from loans.models import Loan
from loans.tests import make_loan, add_repayment
from services.models import ChequebookRequest, KYCDocument
from services.tests import make_bank_branch, make_customer, make_verified_kyc


class CustomerHookBase(TestCase):
    def setUp(self):
        self.bank, self.branch = make_bank_branch()
        self.user, self.customer = make_customer(username="alina")
        self.account = Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="SAVINGS",
            status="ACTIVE", balance=Decimal("20000.00"),
        )
        self.client = Client()
        self.client.login(username="alina", password="testpass123")

    def entries(self, action):
        return AuditLog.objects.filter(action=action)


# ============================================================================
# SERVICES
# ============================================================================

class KYCUploadAuditTestCase(CustomerHookBase):
    def test_uploading_a_document_is_logged(self):
        # Guess: one file field per document, named like the document.
        self.client.post(
            reverse("upload_kyc_document") + "?field=address_proof",
            {"address_proof": SimpleUploadedFile(
                "a.pdf", b"%PDF-1.4 dummy", content_type="application/pdf")},
        )
        entry = self.entries(Actions.KYC_UPLOADED).get()
        self.assertEqual(entry.actor, self.user)
        self.assertEqual(entry.target_type, "KYC")


class ATMRequestAuditTestCase(CustomerHookBase):
    def test_requesting_a_card_is_logged(self):
        make_verified_kyc(self.customer)
        self.client.post(reverse("request_atm_card"), {
            "account": self.account.id, "delivery_address": "123 Test St",
        })
        entry = self.entries(Actions.ATM_REQUESTED).get()
        self.assertEqual(entry.actor, self.user)
        self.assertEqual(entry.target_type, "ATM_CARD_REQUEST")
        self.assertIn(self.account.account_no, entry.details)

    def test_a_blocked_request_is_not_logged(self):
        # No KYC, so the page turns the customer away before anything happens.
        self.client.post(reverse("request_atm_card"), {
            "account": self.account.id, "delivery_address": "123 Test St",
        })
        self.assertEqual(self.entries(Actions.ATM_REQUESTED).count(), 0)


class ChequeAuditTestCase(CustomerHookBase):
    def approved_request(self):
        return ChequebookRequest.objects.create(
            account=self.account, leaf_count=50, status="APPROVED",
            delivery_address="Test Address", cheque_book_fee=Decimal("50.00"),
            fee_charged=False,
        )

    def test_requesting_a_cheque_book_is_logged(self):
        make_verified_kyc(self.customer)
        # Guess: the form uses the fields leaf_count and delivery_address.
        self.client.post(reverse("request_cheque_book"), {
            "account": self.account.id, "leaf_count": 25,
            "delivery_address": "123 Test St",
        })
        entry = self.entries(Actions.CHEQUE_REQUESTED).get()
        self.assertEqual(entry.target_type, "CHEQUE_BOOK_REQUEST")
        self.assertIn("25", entry.details)

    def test_paying_the_fee_is_logged(self):
        req = self.approved_request()
        self.client.post(reverse("confirm_pay_cheque_book_fee", args=[req.id]), {
            "account": self.account.id, "mode_of_transaction": "NETBANKING", "upi_id": "",
        })
        entry = self.entries(Actions.CHEQUE_FEE_PAID).get()
        self.assertEqual(entry.target_id, req.id)
        self.assertIn("50", entry.details)
        self.assertIn("NETBANKING", entry.details)

    def test_the_upi_id_is_never_written_to_the_log(self):
        req = self.approved_request()
        self.client.post(reverse("confirm_pay_cheque_book_fee", args=[req.id]), {
            "account": self.account.id, "mode_of_transaction": "UPI",
            "upi_id": "secret@upi",
        })
        entry = self.entries(Actions.CHEQUE_FEE_PAID).get()
        self.assertNotIn("secret@upi", entry.details)


class StatementAuditTestCase(CustomerHookBase):
    def test_downloading_a_statement_is_logged(self):
        # Guess: the form takes a "period" such as last_30.
        self.client.post(
            reverse("download_account_statement", args=[self.account.id]),
            {"period": "last_30"},
        )
        entry = self.entries(Actions.STATEMENT_DOWNLOADED).get()
        self.assertEqual(entry.actor, self.user)
        self.assertEqual(entry.target_id, self.account.id)


# ============================================================================
# LOANS
# ============================================================================

class LoanCustomerAuditTestCase(CustomerHookBase):
    def test_applying_for_a_loan_is_logged(self):
        kyc = make_verified_kyc(self.customer)
        KYCDocument.objects.create(
            kyc_verification=kyc, document_type="INCOME_PROOF",
            file=SimpleUploadedFile("income.pdf", b"dummy", content_type="application/pdf"),
            verification_status="VERIFIED", verified_at=timezone.now(),
        )
        # The eligibility rules are tested elsewhere, so we let this one through.
        with patch("loans.views.check_eligibility", return_value=(True, [])):
            self.client.post(reverse("apply_loan"), {
                "loan_type": "PERSONAL", "repayment_type": "EMI",
                "amount": "10000", "tenure_months": "12",
                "account": str(self.account.id),
            })
        loan = Loan.objects.get()
        entry = self.entries(Actions.LOAN_APPLIED).get()
        self.assertEqual(entry.target_id, loan.id)
        self.assertIn("10000", entry.details)

    def test_paying_an_emi_is_logged(self):
        loan = make_loan(self.account, self.customer)
        repayment = add_repayment(loan, 1, timezone.localdate(), principal="1000.00")
        self.client.post(reverse("pay_emi", args=[repayment.id]))
        entry = self.entries(Actions.EMI_PAID).get()
        self.assertEqual(entry.target_id, loan.id)
        self.assertIn("Installment 1", entry.details)

    def test_paying_a_lump_sum_is_logged(self):
        loan = make_loan(
            self.account, self.customer, repayment_type="LUMP_SUM",
            lump_sum_total_payable=Decimal("11000.00"),
        )
        self.client.post(reverse("confirm_pay_lump_sum", args=[loan.id]), {
            "amount": "2000", "account": self.account.id,
            "mode_of_transaction": "NETBANKING",
        })
        entry = self.entries(Actions.LUMP_SUM_PAID).get()
        self.assertEqual(entry.target_id, loan.id)
        self.assertIn("2000", entry.details)

    def test_requesting_a_foreclosure_is_logged(self):
        loan = make_loan(self.account, self.customer)
        self.client.post(reverse("request_foreclosure", args=[loan.id]))
        entry = self.entries(Actions.FORECLOSURE_REQUESTED).get()
        self.assertEqual(entry.target_id, loan.id)


# ============================================================================
# TRANSFERS
# ============================================================================

class TransferAuditTestCase(CustomerHookBase):
    def setUp(self):
        super().setUp()
        make_verified_kyc(self.customer)
        bob_user, bob = make_customer(username="bob")
        self.bob_account = Account.objects.create(
            customer=bob, branch=self.branch, account_type="SAVINGS",
            status="ACTIVE", balance=Decimal("5000.00"),
        )

    def transfer(self, amount):
        return self.client.post(reverse("customer_transfer"), {
            "from_account_no": self.account.account_no,
            "to_account_no": self.bob_account.account_no,
            "amount": amount,
        })

    def test_a_completed_transfer_is_logged(self):
        self.transfer("1500.00")
        entry = self.entries(Actions.TRANSFER_SENT).get()
        self.assertEqual(entry.actor, self.user)
        self.assertEqual(entry.target_id, self.account.id)
        self.assertIn("1500", entry.details)

    def test_a_transfer_with_too_little_balance_is_not_logged(self):
        self.transfer("25000.00")
        self.assertEqual(self.entries(Actions.TRANSFER_SENT).count(), 0)


# ============================================================================
# THE ACTION DROPDOWN ON THE AUDIT PAGE
# ============================================================================

class ActionListTestCase(TestCase):
    def setUp(self):
        User.objects.create_superuser(
            username="boss", password="testpass123", email="boss@test.com"
        )
        self.client = Client()
        self.client.login(username="boss", password="testpass123")

    def actions_for(self, user_type=""):
        params = {"user_type": user_type} if user_type else {}
        response = self.client.get(reverse("audit_log"), params)
        return list(response.context["actions"])

    def test_customer_list_has_the_customer_actions_only(self):
        actions = self.actions_for("CUSTOMER")
        for name in ("ATM_REQUESTED", "LOAN_APPLIED", "TRANSFER_SENT", "STATEMENT_DOWNLOADED"):
            self.assertIn(name, actions)
        self.assertNotIn("KYC_VERIFIED", actions)
        self.assertEqual(set(actions), set(CUSTOMER_ACTIONS))

    def test_employee_list_has_staff_actions_and_no_customer_only_ones(self):
        actions = self.actions_for("EMPLOYEE")
        self.assertIn("KYC_VERIFIED", actions)
        self.assertIn("STATEMENT_DOWNLOADED", actions)   # shared with customers
        self.assertNotIn("ATM_REQUESTED", actions)
        self.assertEqual(set(actions), set(STAFF_ACTIONS))

    def test_the_full_list_has_everything(self):
        self.assertEqual(set(self.actions_for()), set(Actions.ALL))