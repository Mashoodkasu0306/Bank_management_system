from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import URLPattern, URLResolver, get_resolver, reverse
import re

from loans.models import LoanDocument
from loans.tests import make_account, make_loan
from services.tests import (
    make_bank_branch, make_customer, make_employee, make_verified_kyc,
)

PDF = b"%PDF-1.4\n% a tiny test file\n"


def login(username):
    client = Client()
    assert client.login(username=username, password="testpass123")
    return client


class DocumentAccessBase(TestCase):
    def setUp(self):
        self.bank, self.branch = make_bank_branch()
        self.owner_user, self.owner = make_customer(username="alina")
        self.other_user, self.other = make_customer(username="bob")
        self.emp_user, self.emp = make_employee(self.branch, username="kyc_emp", department="KYC")
        self.admin = User.objects.create_user(username="boss", password="testpass123")

        kyc = make_verified_kyc(self.owner)
        self.kyc_doc = kyc.documents.first()
        self.kyc_doc.file = SimpleUploadedFile("id.pdf", PDF, content_type="application/pdf")
        self.kyc_doc.save()

        account = make_account(self.branch, self.owner)
        self.loan = make_loan(account, self.owner)
        self.loan_doc = LoanDocument.objects.create(
            loan=self.loan, document_type="ID_PROOF",
            file=SimpleUploadedFile("proof.pdf", PDF, content_type="application/pdf"),
        )

        self.kyc_url = reverse("kyc_document_download", args=[self.kyc_doc.id])
        self.loan_url = reverse("loan_document_download", args=[self.loan_doc.id])


class KYCDocumentAccessTests(DocumentAccessBase):
    def test_owner_can_open_own_document(self):
        response = login("alina").get(self.kyc_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), PDF)

    def test_download_is_never_cached(self):
        response = login("alina").get(self.kyc_url)
        self.assertIn("no-store", response["Cache-Control"])

    def test_another_customer_gets_404(self):
        self.assertEqual(login("bob").get(self.kyc_url).status_code, 404)

    def test_logged_out_visitor_is_sent_to_login(self):
        response = Client().get(self.kyc_url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"].split("?")[0], reverse("login"))

    def test_employee_can_open(self):
        self.assertEqual(login("kyc_emp").get(self.kyc_url).status_code, 200)

    def test_admin_can_open(self):
        self.assertEqual(login("boss").get(self.kyc_url).status_code, 200)

    def test_unknown_document_is_404(self):
        url = reverse("kyc_document_download", args=[999999])
        self.assertEqual(login("kyc_emp").get(url).status_code, 404)


class LoanDocumentAccessTests(DocumentAccessBase):
    def test_owner_can_open_own_document(self):
        response = login("alina").get(self.loan_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), PDF)

    def test_another_customer_gets_404(self):
        self.assertEqual(login("bob").get(self.loan_url).status_code, 404)

    def test_logged_out_visitor_is_sent_to_login(self):
        response = Client().get(self.loan_url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"].split("?")[0], reverse("login"))

    def test_employee_can_open(self):
        self.assertEqual(login("kyc_emp").get(self.loan_url).status_code, 200)

    def test_admin_can_open(self):
        self.assertEqual(login("boss").get(self.loan_url).status_code, 200)


class NoPublicMediaTests(DocumentAccessBase):
    def test_media_route_is_gone_from_project_urls(self):
        source = (Path(settings.BASE_DIR) / "bank_management" / "urls.py").read_text(encoding="utf-8")
        self.assertNotIn("static(", source)
        self.assertNotIn("MEDIA", source)

    def test_staff_kyc_page_links_to_private_download(self):
        url = reverse("review_customer_kyc", args=[self.owner.id])
        html = login("kyc_emp").get(url).content.decode()
        self.assertIn(self.kyc_url, html)
        self.assertNotIn("/media/", html)

    def test_loan_page_links_to_private_download(self):
        url = reverse("loan_detail", args=[self.loan.id])
        html = login("alina").get(url).content.decode()
        self.assertIn(self.loan_url, html)
        self.assertNotIn("/media/", html)


# ============================================================================
# A STRANGER VISITS EVERY URL
# ============================================================================

def collect_paths(patterns=None, prefix=""):
    patterns = patterns if patterns is not None else get_resolver().url_patterns
    found = []
    for p in patterns:
        route = str(p.pattern)
        if isinstance(p, URLResolver):
            found += collect_paths(p.url_patterns, prefix + route)
        elif isinstance(p, URLPattern):
            found.append(prefix + route)
    return found


def fill_in(path):
    path = re.sub(r"<int:[^>]+>", "1", path)
    path = re.sub(r"<[^>]+>", "x", path)
    return "/" + path


class StrangerVisitsEveryUrlTests(TestCase):
    def public_paths(self):
        return {
            reverse("login"),
            reverse("pwa_service_worker"),
            reverse("pwa_offline"),
            "/manifest.webmanifest",  # PWA manifest: browsers fetch it without logging in
            # Add other pages that are meant to be public here.
        }

    def test_logged_out_visitor_is_sent_to_login_everywhere(self):
        login_path = reverse("login")
        public = self.public_paths()
        offenders = []
        for raw in sorted(set(collect_paths())):
            if raw.startswith("admin/") or any(c in raw for c in "^($"):
                continue
            path = fill_in(raw)
            if path in public:
                continue
            try:
                response = self.client.get(path)
            except Exception as exc:
                offenders.append("%s -> crashed (%s)" % (path, type(exc).__name__))
                continue
            if response.status_code == 302 and response["Location"].split("?")[0] == login_path:
                continue
            offenders.append("%s -> %s" % (path, response.status_code))
        self.assertEqual(offenders, [], "Open to strangers:\n" + "\n".join(offenders))