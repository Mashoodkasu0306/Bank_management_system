from decimal import Decimal
from datetime import timedelta
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from bank.models import Bank, Branch
from users.models import Customer, Employee
from accounts.models import Account
from transactions.models import Transaction

from services.models import (
    KYCVerification, KYCDocument, ATMCardRequest, ChequebookRequest, AccountStatement
)
from services.helpers import (
    check_atm_card_eligibility, check_cheque_book_eligibility,
    get_statement_transactions, calculate_statement_balances,
    get_preset_date_range
)


def make_bank_branch():
    bank = Bank.objects.create(name="Test Bank", code="TB01")
    branch = Branch.objects.create(
        bank=bank, name="Main Branch", branch_code="BR01",
        address="123 Test St", city="Test City", state="Test State",
        ifsc_code="TB0100001"
    )
    return bank, branch


def make_customer(username="cust1", password="testpass123"):
    user = User.objects.create_user(username=username, password=password)
    customer = Customer.objects.create(
        user=user, customer_type="INDIVIDUAL", dob="1990-01-01",
        gender="MALE", address="Test Address", kyc_status="PENDING"
    )
    return user, customer


def make_employee(branch, username="emp1", password="testpass123", department=""):
    user = User.objects.create_user(username=username, password=password)
    employee = Employee.objects.create(
        user=user, branch=branch, role="Clerk", department=department,
        salary=Decimal("30000.00"), date_of_joining="2020-01-01"
    )
    return user, employee


def make_verified_kyc(customer):
    """Helper: create a KYC record with all 3 mandatory docs VERIFIED."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    kyc = KYCVerification.objects.create(customer=customer, status="VERIFIED", verified_at=timezone.now())
    for doc_type in ["ID_PROOF", "PAN", "ADDRESS_PROOF"]:
        KYCDocument.objects.create(
            kyc_verification=kyc,
            document_type=doc_type,
            file=SimpleUploadedFile(f"{doc_type}.pdf", b"dummy content", content_type="application/pdf"),
            verification_status="VERIFIED",
            verified_at=timezone.now(),
        )
    return kyc


# ============================================================================
# ATM CARD ELIGIBILITY TESTS
# ============================================================================

class ATMCardEligibilityTestCase(TestCase):
    def setUp(self):
        self.bank, self.branch = make_bank_branch()
        self.user, self.customer = make_customer()
        self.kyc = make_verified_kyc(self.customer)

    def test_eligible_active_savings_account_with_verified_kyc(self):
        account = Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="SAVINGS",
            status="ACTIVE", balance=Decimal("5000.00")
        )
        is_eligible, reason = check_atm_card_eligibility(account)
        self.assertTrue(is_eligible)
        self.assertEqual(reason, "")

    def test_ineligible_when_account_not_active(self):
        account = Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="SAVINGS",
            status="CLOSED", balance=Decimal("5000.00")
        )
        is_eligible, reason = check_atm_card_eligibility(account)
        self.assertFalse(is_eligible)
        self.assertIn("active", reason.lower())

    def test_ineligible_for_loan_account_type(self):
        account = Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="LOAN",
            status="ACTIVE", balance=Decimal("5000.00")
        )
        is_eligible, reason = check_atm_card_eligibility(account)
        self.assertFalse(is_eligible)
        self.assertIn("not eligible", reason.lower())

    def test_ineligible_when_kyc_not_verified(self):
        user2, customer2 = make_customer(username="cust2")
        KYCVerification.objects.create(customer=customer2, status="PENDING")
        account = Account.objects.create(
            customer=customer2, branch=self.branch, account_type="SAVINGS",
            status="ACTIVE", balance=Decimal("5000.00")
        )
        is_eligible, reason = check_atm_card_eligibility(account)
        self.assertFalse(is_eligible)
        self.assertIn("kyc", reason.lower())

    def test_ineligible_with_existing_pending_request(self):
        account = Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="SAVINGS",
            status="ACTIVE", balance=Decimal("5000.00")
        )
        ATMCardRequest.objects.create(account=account, status="PENDING", delivery_address="Test Address")

        is_eligible, reason = check_atm_card_eligibility(account)
        self.assertFalse(is_eligible)
        self.assertIn("already have", reason.lower())

    def test_atm_card_can_be_rejected_twice(self):
        """
        Regression test: a customer whose ATM card request is rejected must
        be able to submit (and be rejected again on) a new request for the
        same account. Would fail if ATMCardRequest ever re-gains a DB
        unique_together on (account, status).
        """
        account = Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="SAVINGS",
            status="ACTIVE", balance=Decimal("10000.00")
        )
        ATMCardRequest.objects.create(
            account=account, status="REJECTED",
            delivery_address="Test Address", rejection_reason="Blurry ID"
        )
        second = ATMCardRequest.objects.create(
            account=account, status="REJECTED",
            delivery_address="Test Address 2", rejection_reason="Still blurry"
        )
        self.assertEqual(
            ATMCardRequest.objects.filter(account=account, status="REJECTED").count(), 2
        )
        self.assertEqual(second.status, "REJECTED")


# ============================================================================
# CHEQUE BOOK ELIGIBILITY TESTS
# (No account-age requirement — that rule applies to LOANS only, via
# LoanEligibilityRule.min_account_age_days. Cheque books and ATM cards
# have no age requirement.)
# ============================================================================

class ChequebookEligibilityTestCase(TestCase):
    def setUp(self):
        self.bank, self.branch = make_bank_branch()
        self.user, self.customer = make_customer()

    def test_eligible_new_savings_account_sufficient_balance(self):
        account = Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="SAVINGS",
            status="ACTIVE", balance=Decimal("2000.00")
        )
        # open_date defaults to today (auto_now_add) — brand new account, still eligible
        is_eligible, reason = check_cheque_book_eligibility(account)
        self.assertTrue(is_eligible)

    def test_ineligible_for_loan_account_type(self):
        account = Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="LOAN",
            status="ACTIVE", balance=Decimal("2000.00")
        )
        is_eligible, reason = check_cheque_book_eligibility(account)
        self.assertFalse(is_eligible)
        self.assertIn("not eligible", reason.lower())

    def test_ineligible_insufficient_balance(self):
        account = Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="SAVINGS",
            status="ACTIVE", balance=Decimal("500.00")
        )
        is_eligible, reason = check_cheque_book_eligibility(account)
        self.assertFalse(is_eligible)
        self.assertIn("1,000", reason)

    def test_ineligible_duplicate_pending_request(self):
        account = Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="SAVINGS",
            status="ACTIVE", balance=Decimal("2000.00")
        )
        ChequebookRequest.objects.create(
            account=account, leaf_count=25, status="PENDING", delivery_address="Test Address"
        )
        is_eligible, reason = check_cheque_book_eligibility(account)
        self.assertFalse(is_eligible)
        self.assertIn("already have", reason.lower())

    def test_eligible_again_after_previous_request_rejected(self):
        """A rejected request should NOT block a new one."""
        account = Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="SAVINGS",
            status="ACTIVE", balance=Decimal("2000.00")
        )
        ChequebookRequest.objects.create(
            account=account, leaf_count=25, status="REJECTED",
            delivery_address="Test Address", rejection_reason="Test"
        )
        is_eligible, reason = check_cheque_book_eligibility(account)
        self.assertTrue(is_eligible)


# ============================================================================
# STATEMENT CALCULATION TESTS
# ============================================================================

class StatementCalculationTestCase(TestCase):
    def setUp(self):
        self.bank, self.branch = make_bank_branch()
        self.user, self.customer = make_customer()
        self.account = Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="SAVINGS",
            status="ACTIVE", balance=Decimal("0.00")
        )

    def test_opening_and_closing_balance_with_deposits_and_withdrawals(self):
        today = timezone.localdate()

        old_txn = Transaction.objects.create(
            transaction_type="DEPOSIT", to_account=self.account, amount=Decimal("1000.00"),
            status="SUCCESS"
        )
        old_txn.timestamp = timezone.now() - timedelta(days=40)
        old_txn.save()

        deposit_txn = Transaction.objects.create(
            transaction_type="DEPOSIT", to_account=self.account, amount=Decimal("500.00"),
            status="SUCCESS"
        )
        deposit_txn.timestamp = timezone.now() - timedelta(days=10)
        deposit_txn.save()

        withdraw_txn = Transaction.objects.create(
            transaction_type="WITHDRAW", from_account=self.account, amount=Decimal("200.00"),
            status="SUCCESS"
        )
        withdraw_txn.timestamp = timezone.now() - timedelta(days=5)
        withdraw_txn.save()

        start_date = today - timedelta(days=30)
        end_date = today

        transactions = get_statement_transactions(self.account, start_date, end_date)
        self.assertEqual(transactions.count(), 2)

        opening, closing = calculate_statement_balances(self.account, transactions, start_date)
        self.assertEqual(opening, Decimal("1000.00"))
        self.assertEqual(closing, Decimal("1300.00"))

    def test_failed_transactions_excluded(self):
        today = timezone.localdate()
        Transaction.objects.create(
            transaction_type="DEPOSIT", to_account=self.account, amount=Decimal("999.00"),
            status="FAILED"
        )
        transactions = get_statement_transactions(self.account, today - timedelta(days=5), today)
        self.assertEqual(transactions.count(), 0)

    def test_preset_date_ranges(self):
        today = timezone.localdate()
        start, end = get_preset_date_range("last_30")
        self.assertEqual(end, today)
        self.assertEqual((end - start).days, 30)

        start, end = get_preset_date_range("last_365")
        self.assertEqual((end - start).days, 365)


# ============================================================================
# OWNERSHIP / PERMISSION TESTS
# ============================================================================

class OwnershipTestCase(TestCase):
    def setUp(self):
        self.bank, self.branch = make_bank_branch()
        self.user1, self.customer1 = make_customer(username="owner")
        self.user2, self.customer2 = make_customer(username="intruder")
        self.emp_user, self.employee = make_employee(self.branch)

        self.account = Account.objects.create(
            customer=self.customer1, branch=self.branch, account_type="SAVINGS",
            status="ACTIVE", balance=Decimal("5000.00")
        )
        self.atm_request = ATMCardRequest.objects.create(
            account=self.account, status="PENDING", delivery_address="Test Address"
        )
        self.cheque_request = ChequebookRequest.objects.create(
            account=self.account, leaf_count=25, status="PENDING", delivery_address="Test Address"
        )

        self.client = Client()

    def test_customer_cannot_view_another_customers_atm_request(self):
        self.client.login(username="intruder", password="testpass123")
        response = self.client.get(reverse("atm_card_status", args=[self.atm_request.id]))
        self.assertEqual(response.status_code, 302)

    def test_owner_can_view_their_own_atm_request(self):
        self.client.login(username="owner", password="testpass123")
        response = self.client.get(reverse("atm_card_status", args=[self.atm_request.id]))
        self.assertEqual(response.status_code, 200)

    def test_customer_cannot_view_another_customers_cheque_request(self):
        self.client.login(username="intruder", password="testpass123")
        response = self.client.get(reverse("cheque_book_status", args=[self.cheque_request.id]))
        self.assertEqual(response.status_code, 302)

    def test_customer_cannot_download_another_customers_statement(self):
        self.client.login(username="intruder", password="testpass123")
        response = self.client.get(reverse("download_account_statement", args=[self.account.id]))
        self.assertEqual(response.status_code, 302)

    def test_owner_can_access_their_own_statement_page(self):
        self.client.login(username="owner", password="testpass123")
        response = self.client.get(reverse("download_account_statement", args=[self.account.id]))
        self.assertEqual(response.status_code, 200)

    def test_staff_can_access_any_customers_statement_page(self):
        self.client.login(username="emp1", password="testpass123")
        response = self.client.get(reverse("download_account_statement", args=[self.account.id]))
        self.assertEqual(response.status_code, 200)

    def test_customer_cannot_access_staff_approval_pages(self):
        self.client.login(username="owner", password="testpass123")
        response = self.client.get(reverse("pending_kyc_documents"))
        self.assertEqual(response.status_code, 302)

    def test_staff_can_access_approval_pages(self):
        self.client.login(username="emp1", password="testpass123")
        response = self.client.get(reverse("pending_kyc_documents"))
        self.assertEqual(response.status_code, 200)


# ============================================================================
# DUPLICATE REQUEST PREVENTION
# ============================================================================

class DuplicateRequestTestCase(TestCase):
    def setUp(self):
        self.bank, self.branch = make_bank_branch()
        self.user, self.customer = make_customer()
        make_verified_kyc(self.customer)

        self.account = Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="SAVINGS",
            status="ACTIVE", balance=Decimal("5000.00")
        )
        self.client = Client()
        self.client.login(username="cust1", password="testpass123")

    def test_second_atm_request_blocked_via_view(self):
        self.client.post(reverse("request_atm_card"), {
            "account": self.account.id,
            "delivery_address": "123 Test St",
        })
        self.assertEqual(ATMCardRequest.objects.filter(account=self.account).count(), 1)

        self.client.post(reverse("request_atm_card"), {
            "account": self.account.id,
            "delivery_address": "123 Test St",
        })
        self.assertEqual(ATMCardRequest.objects.filter(account=self.account).count(), 1)


# ============================================================================
# APPROVAL WORKFLOW TESTS
# ============================================================================

class ApprovalWorkflowTestCase(TestCase):
    def setUp(self):
        self.bank, self.branch = make_bank_branch()
        self.user, self.customer = make_customer()
        self.emp_user, self.employee = make_employee(self.branch)

        self.account = Account.objects.create(
            customer=self.customer, branch=self.branch, account_type="SAVINGS",
            status="ACTIVE", balance=Decimal("5000.00")
        )
        self.client = Client()

    def test_kyc_document_approval_updates_overall_status(self):
        kyc = KYCVerification.objects.create(customer=self.customer)
        from django.core.files.uploadedfile import SimpleUploadedFile

        doc = KYCDocument.objects.create(
            kyc_verification=kyc, document_type="ID_PROOF",
            file=SimpleUploadedFile("id.pdf", b"dummy", content_type="application/pdf"),
        )

        self.client.login(username="emp1", password="testpass123")
        self.client.post(reverse("verify_kyc_document", args=[doc.id]), {
            "verification_status": "VERIFIED",
            "reviewer_notes": "Looks good",
        })

        doc.refresh_from_db()
        self.assertEqual(doc.verification_status, "VERIFIED")
        self.assertIsNotNone(doc.verified_at)
        self.assertEqual(doc.verified_by, self.emp_user)

    def test_kyc_rejection_requires_reason(self):
        kyc = KYCVerification.objects.create(customer=self.customer)
        from django.core.files.uploadedfile import SimpleUploadedFile

        doc = KYCDocument.objects.create(
            kyc_verification=kyc, document_type="ID_PROOF",
            file=SimpleUploadedFile("id.pdf", b"dummy", content_type="application/pdf"),
        )

        self.client.login(username="emp1", password="testpass123")
        self.client.post(reverse("verify_kyc_document", args=[doc.id]), {
            "verification_status": "REJECTED",
            "rejection_reason": "",
        })

        doc.refresh_from_db()
        self.assertEqual(doc.verification_status, "PENDING")

    def test_cheque_book_approval_with_fee_requires_customer_payment(self):
        """Approval with a nonzero fee no longer deducts anything — it just
        marks the request APPROVED and awaiting the customer's own payment."""
        cheque_request = ChequebookRequest.objects.create(
            account=self.account, leaf_count=50, status="PENDING", delivery_address="Test Address"
        )

        self.client.login(username="emp1", password="testpass123")
        self.client.post(reverse("approve_cheque_book_request", args=[cheque_request.id]), {
            "approval_status": "APPROVED",
            "cheque_book_fee": "50.00",
        })

        cheque_request.refresh_from_db()
        self.account.refresh_from_db()

        self.assertEqual(cheque_request.status, "APPROVED")
        self.assertFalse(cheque_request.fee_charged)
        self.assertEqual(self.account.balance, Decimal("5000.00"))

        self.client.logout()
        self.client.login(username="cust1", password="testpass123")
        self.client.post(reverse("pay_cheque_book_fee", args=[cheque_request.id]), {
            "account_netbanking": self.account.id,
            "mode_of_transaction": "NETBANKING",
        })
        self.client.post(reverse("confirm_pay_cheque_book_fee", args=[cheque_request.id]), {
            "account": self.account.id,
            "mode_of_transaction": "NETBANKING",
            "upi_id": "",
        })

        cheque_request.refresh_from_db()
        self.account.refresh_from_db()

        self.assertEqual(cheque_request.status, "PROCESSING")
        self.assertTrue(cheque_request.fee_charged)
        self.assertEqual(self.account.balance, Decimal("4950.00"))

        txn = Transaction.objects.filter(from_account=self.account, transaction_type="WITHDRAW").first()
        self.assertIsNotNone(txn)
        self.assertEqual(txn.amount, Decimal("50.00"))

    def test_cheque_book_approval_zero_fee_auto_processes(self):
        """A zero fee skips the payment step entirely and goes straight to PROCESSING."""
        cheque_request = ChequebookRequest.objects.create(
            account=self.account, leaf_count=25, status="PENDING", delivery_address="Test Address"
        )

        self.client.login(username="emp1", password="testpass123")
        self.client.post(reverse("approve_cheque_book_request", args=[cheque_request.id]), {
            "approval_status": "APPROVED",
            "cheque_book_fee": "0.00",
        })

        cheque_request.refresh_from_db()
        self.account.refresh_from_db()

        self.assertEqual(cheque_request.status, "PROCESSING")
        self.assertTrue(cheque_request.fee_charged)
        self.assertEqual(self.account.balance, Decimal("5000.00"))
        self.assertFalse(
            Transaction.objects.filter(from_account=self.account, transaction_type="WITHDRAW").exists()
        )

    def test_atm_approval_auto_generates_card_details(self):
        """Card number/CVV/expiry are auto-generated on approval, not staff-entered."""
        atm_request = ATMCardRequest.objects.create(
            account=self.account, status="PENDING", delivery_address="Test Address"
        )
        self.client.login(username="emp1", password="testpass123")
        self.client.post(reverse("approve_atm_card_request", args=[atm_request.id]), {
            "approval_status": "APPROVED",
        })

        atm_request.refresh_from_db()
        self.assertEqual(atm_request.status, "APPROVED")
        self.assertTrue(atm_request.masked_card_number.startswith("XXXX-XXXX-XXXX-"))
        self.assertEqual(len(atm_request.masked_card_number.split("-")[-1]), 4)
        self.assertIsNotNone(atm_request.expiry_date)

    def test_generated_card_number_passes_luhn_check(self):
        from services.helpers import generate_card_number
        number = generate_card_number()
        self.assertEqual(len(number), 16)
        self.assertTrue(number.isdigit())

        digits = [int(d) for d in number]
        digits.reverse()
        total = 0
        for i, d in enumerate(digits):
            if i % 2 == 1:
                d *= 2
                if d > 9:
                    d -= 9
            total += d
        self.assertEqual(total % 10, 0)