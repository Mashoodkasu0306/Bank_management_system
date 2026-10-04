from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import reverse

from notifications.helpers import notify_staff
from notifications.models import Notification
from services.models import KYCVerification, KYCDocument
from services.tests import make_bank_branch, make_customer, make_employee

TITLE = "KYC documents submitted for review"


class KYCNotificationClearingTestCase(TestCase):
    def setUp(self):
        self.bank, self.branch = make_bank_branch()
        self.ali_user, self.ali = make_customer(username="ali")
        self.alina_user, self.alina = make_customer(username="alina")
        self.emp_user, self.employee = make_employee(self.branch, department="KYC")

        self.ali_kyc = KYCVerification.objects.create(customer=self.ali)
        self.alina_kyc = KYCVerification.objects.create(customer=self.alina)
        self.ali_doc = self.make_doc(self.ali_kyc, "ID_PROOF")
        self.alina_doc = self.make_doc(self.alina_kyc, "ID_PROOF")

        self.client = Client()
        self.client.login(username="emp1", password="testpass123")

    def make_doc(self, kyc, doc_type):
        return KYCDocument.objects.create(
            kyc_verification=kyc, document_type=doc_type,
            file=SimpleUploadedFile(f"{doc_type}.pdf", b"dummy", content_type="application/pdf"),
        )

    def staff_notify(self, name, kyc=None):
        kwargs = {}
        if kyc is not None:
            kwargs = {"related_type": "KYC", "related_id": kyc.id}
        notify_staff("KYC", TITLE, f"{name} submitted 1 document(s): ID Proof (uploaded).", **kwargs)

    def unread(self, name):
        return Notification.objects.filter(
            category="KYC", is_read=False, message__startswith=f"{name} submitted"
        ).count()

    def verify(self, doc):
        self.client.post(reverse("verify_kyc_document", args=[doc.id]), {
            "verification_status": "VERIFIED", "reviewer_notes": "ok",
        })

    def test_tagged_notifications_clear_only_for_the_right_customer(self):
        self.staff_notify("ali", self.ali_kyc)
        self.staff_notify("alina", self.alina_kyc)
        self.verify(self.ali_doc)
        self.assertEqual(self.unread("ali"), 0)
        self.assertEqual(self.unread("alina"), 1)

    def test_old_untagged_notifications_do_not_mix_up_similar_names(self):
        self.staff_notify("ali")
        self.staff_notify("alina")
        self.verify(self.ali_doc)
        self.assertEqual(self.unread("ali"), 0)
        self.assertEqual(self.unread("alina"), 1)

    def test_nothing_is_cleared_while_another_document_is_still_pending(self):
        self.make_doc(self.ali_kyc, "PAN")
        self.staff_notify("ali", self.ali_kyc)
        self.verify(self.ali_doc)
        self.assertEqual(self.unread("ali"), 1)