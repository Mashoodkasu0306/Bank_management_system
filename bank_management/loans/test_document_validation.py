from decimal import Decimal
from unittest.mock import patch

from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditLog, Actions
from loans.models import Loan, LoanDocument
from loans.tests import make_account, make_loan
from services.models import KYCDocument
from services.tests import make_bank_branch, make_customer, make_verified_kyc

# Tiny stand-ins that start the way real files of each kind start.
PDF = b"%PDF-1.4\n% a tiny test file\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20
EXE = b"MZ\x90\x00\x03\x00\x00\x00 this is a program, not a document"


def upload(name, content):
    return SimpleUploadedFile(name, content)


class LoanDocumentBase(TestCase):
    def setUp(self):
        self.bank, self.branch = make_bank_branch()
        self.user, self.customer = make_customer(username="alina")
        self.account = make_account(self.branch, self.customer)
        self.client = Client()
        self.client.login(username="alina", password="testpass123")

    def message_texts(self, response):
        return [str(m) for m in get_messages(response.wsgi_request)]


# ============================================================================
# APPLYING FOR A LOAN WITH A DOCUMENT
# ============================================================================

class ApplyLoanDocumentTestCase(LoanDocumentBase):
    def setUp(self):
        super().setUp()
        kyc = make_verified_kyc(self.customer)
        KYCDocument.objects.create(
            kyc_verification=kyc, document_type="INCOME_PROOF",
            file=upload("income.pdf", PDF),
            verification_status="VERIFIED", verified_at=timezone.now(),
        )

    def apply(self, **files):
        data = {
            "loan_type": "PERSONAL", "repayment_type": "EMI",
            "amount": "10000", "tenure_months": "12",
            "account": str(self.account.id), "document_type": "ID_PROOF",
        }
        data.update(files)
        # The eligibility rules are tested elsewhere, so we let this one through.
        with patch("loans.views.check_eligibility", return_value=(True, [])):
            return self.client.post(reverse("apply_loan"), data)

    def test_a_real_pdf_is_accepted(self):
        response = self.apply(document=upload("proof.pdf", PDF))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Loan.objects.count(), 1)
        self.assertEqual(LoanDocument.objects.count(), 1)

    def test_a_pdf_with_fake_contents_is_refused_and_nothing_is_saved(self):
        response = self.apply(document=upload("fake.pdf", EXE))
        self.assertEqual(Loan.objects.count(), 0)
        self.assertEqual(LoanDocument.objects.count(), 0)
        self.assertEqual(AuditLog.objects.filter(action=Actions.LOAN_APPLIED).count(), 0)
        self.assertTrue(any("do not match" in text for text in self.message_texts(response)))

    def test_a_program_is_refused_and_nothing_is_saved(self):
        self.apply(document=upload("virus.exe", EXE))
        self.assertEqual(Loan.objects.count(), 0)
        self.assertEqual(LoanDocument.objects.count(), 0)

    def test_applying_without_a_document_still_works(self):
        response = self.apply()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Loan.objects.count(), 1)
        self.assertEqual(LoanDocument.objects.count(), 0)


# ============================================================================
# ADDING A DOCUMENT TO A LOAN THAT IS STILL PENDING
# ============================================================================

class UploadLoanDocumentTestCase(LoanDocumentBase):
    def setUp(self):
        super().setUp()
        self.loan = make_loan(
            self.account, self.customer, status="PENDING", approved_date=None
        )
        self.url = reverse("upload_loan_document", args=[self.loan.id])

    def send(self, name, content):
        return self.client.post(self.url, {
            "document": upload(name, content), "document_type": "ID_PROOF",
        })

    def test_a_real_pdf_is_accepted(self):
        self.send("proof.pdf", PDF)
        self.assertEqual(LoanDocument.objects.filter(loan=self.loan).count(), 1)

    def test_a_real_png_is_accepted(self):
        self.send("proof.png", PNG)
        self.assertEqual(LoanDocument.objects.filter(loan=self.loan).count(), 1)

    def test_a_pdf_with_fake_contents_is_refused(self):
        response = self.send("fake.pdf", EXE)
        self.assertEqual(LoanDocument.objects.count(), 0)
        self.assertTrue(any("do not match" in text for text in self.message_texts(response)))

    def test_a_pdf_renamed_to_png_is_refused(self):
        self.send("proof.png", PDF)
        self.assertEqual(LoanDocument.objects.count(), 0)

    def test_a_file_over_5mb_is_still_refused(self):
        self.send("big.pdf", PDF + b"0" * (5 * 1024 * 1024))
        self.assertEqual(LoanDocument.objects.count(), 0)