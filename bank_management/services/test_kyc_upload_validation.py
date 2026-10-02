from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import reverse

from audit.models import AuditLog, Actions
from services.forms import KYCDocumentUploadForm
from services.models import KYCDocument
from services.tests import make_bank_branch, make_customer

# Tiny stand-ins that start the way real files of each kind start.
PDF = b"%PDF-1.4\n% a tiny test file\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 20
EXE = b"MZ\x90\x00\x03\x00\x00\x00 this is a program, not a document"


def upload(name, content):
    return SimpleUploadedFile(name, content)


def build_form(field="id_proof", name="id.pdf", content=PDF, **kwargs):
    return KYCDocumentUploadForm({}, {field: upload(name, content)}, **kwargs)


def error_text(form):
    return " ".join(form.non_field_errors())


# ============================================================================
# THE FORM ITSELF
# ============================================================================

class DocumentFileCheckTestCase(TestCase):
    def test_a_real_pdf_is_accepted(self):
        form = build_form(name="id.pdf", content=PDF)
        self.assertTrue(form.is_valid(), form.errors)
        documents = form.get_uploaded_documents()
        self.assertEqual([doc_type for doc_type, _ in documents], ["ID_PROOF"])

    def test_a_real_png_is_accepted(self):
        self.assertTrue(build_form(name="id.png", content=PNG).is_valid())

    def test_a_real_jpeg_is_accepted_with_either_spelling(self):
        self.assertTrue(build_form(name="id.jpg", content=JPEG).is_valid())
        self.assertTrue(build_form(name="id.jpeg", content=JPEG).is_valid())

    def test_capital_letters_in_the_extension_are_fine(self):
        self.assertTrue(build_form(name="ID.PDF", content=PDF).is_valid())

    def test_a_program_is_refused(self):
        form = build_form(name="virus.exe", content=EXE)
        self.assertFalse(form.is_valid())
        self.assertIn("Unsupported file type", error_text(form))

    def test_a_program_renamed_to_pdf_is_refused(self):
        form = build_form(name="virus.pdf", content=EXE)
        self.assertFalse(form.is_valid())
        self.assertIn("do not match", error_text(form))

    def test_a_pdf_renamed_to_png_is_refused(self):
        form = build_form(name="id.png", content=PDF)
        self.assertFalse(form.is_valid())
        self.assertIn("do not match", error_text(form))

    def test_a_file_with_no_extension_is_refused(self):
        form = build_form(name="idproof", content=PDF)
        self.assertFalse(form.is_valid())
        self.assertIn("Unsupported file type", error_text(form))

    def test_a_file_over_5mb_is_still_refused(self):
        form = build_form(name="big.pdf", content=PDF + b"0" * (5 * 1024 * 1024))
        self.assertFalse(form.is_valid())
        self.assertIn("5MB", error_text(form))

    def test_one_bad_file_blocks_the_whole_upload(self):
        form = KYCDocumentUploadForm({}, {
            "id_proof": upload("id.pdf", PDF),
            "pan": upload("pan.exe", EXE),
        })
        self.assertFalse(form.is_valid())
        self.assertIn("PAN Card", error_text(form))

    def test_single_document_mode_checks_the_file_too(self):
        form = build_form(
            field="address_proof", name="a.exe", content=EXE, only_field="address_proof"
        )
        self.assertFalse(form.is_valid())


# ============================================================================
# THE REAL UPLOAD PAGE
# ============================================================================

class UploadPageTestCase(TestCase):
    def setUp(self):
        self.bank, self.branch = make_bank_branch()
        self.user, self.customer = make_customer(username="alina")
        self.client = Client()
        self.client.login(username="alina", password="testpass123")
        self.url = reverse("upload_kyc_document") + "?field=address_proof"

    def test_a_fake_document_saves_nothing(self):
        response = self.client.post(self.url, {"address_proof": upload("fake.pdf", EXE)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(KYCDocument.objects.count(), 0)
        self.assertEqual(AuditLog.objects.filter(action=Actions.KYC_UPLOADED).count(), 0)

    def test_a_real_document_is_still_accepted(self):
        response = self.client.post(self.url, {"address_proof": upload("proof.pdf", PDF)})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(KYCDocument.objects.count(), 1)