from decimal import Decimal
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from users.models import Customer
from accounts.models import Account


# ============================================================================
# EXISTING MODELS (kept — restored so nothing is lost from your current file)
# ============================================================================

class Service(models.Model):
    name = models.CharField(max_length=100)
    status = models.CharField(
        max_length=20,
        choices=[("ACTIVE", "Active"), ("INACTIVE", "Inactive")]
    )
    issue_date = models.DateField(auto_now_add=True)

    def __str__(self):
        return self.name


class ServiceUsage(models.Model):
    service = models.ForeignKey(Service, on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    used_at = models.DateTimeField(auto_now_add=True)


# ============================================================================
# VALIDATORS
# ============================================================================

def validate_document_extension(file):
    import os
    ext = os.path.splitext(file.name)[1].lower()
    allowed = [".pdf", ".jpg", ".jpeg", ".png"]
    if ext not in allowed:
        raise ValidationError("Unsupported file type. Allowed: PDF, JPG, JPEG, PNG.")


def validate_document_size(file):
    max_size_mb = 5
    if file.size > max_size_mb * 1024 * 1024:
        raise ValidationError(f"File too large. Maximum size is {max_size_mb}MB.")


# ============================================================================
# KYC VERIFICATION
# ============================================================================

class KYCVerification(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("PARTIALLY_VERIFIED", "Partially Verified"),
        ("VERIFIED", "Verified"),
        ("REJECTED", "Rejected"),
    ]

    customer = models.OneToOneField(Customer, on_delete=models.CASCADE, related_name="kyc_verification")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="verified_kyc"
    )
    rejection_reason = models.TextField(blank=True, help_text="If rejected, why?")

    def __str__(self):
        return f"KYC {self.customer.user.username} - {self.status}"

    def is_fully_verified(self):
        mandatory_types = ["ID_PROOF", "PAN", "ADDRESS_PROOF"]
        for doc_type in mandatory_types:
            doc = self.documents.filter(document_type=doc_type, verification_status="VERIFIED").first()
            if not doc:
                return False
        return True

    def is_missing_income_proof(self):
        income_docs = self.documents.filter(document_type="INCOME_PROOF", verification_status="VERIFIED")
        return not income_docs.exists()

    def update_overall_status(self):
        if self.status == "REJECTED":
            return

        verified_count = self.documents.filter(verification_status="VERIFIED").count()
        total_count = self.documents.count()

        if total_count == 0:
            self.status = "PENDING"
        elif verified_count == total_count:
            self.status = "VERIFIED"
            if not self.verified_at:
                self.verified_at = timezone.now()
        else:
            self.status = "PARTIALLY_VERIFIED"

        self.save(update_fields=["status", "verified_at"])


class KYCDocument(models.Model):
    DOCUMENT_TYPES = [
        ("ID_PROOF", "Government ID (Aadhaar/Passport)"),
        ("PAN", "PAN Card"),
        ("ADDRESS_PROOF", "Address Proof (Aadhaar/Passport/DL/Voter ID/Utility Bill)"),
        ("INCOME_PROOF", "Income Proof (Payslip/Bank Statement/ITR/GST/Business Reg)"),
    ]

    VERIFICATION_STATUS_CHOICES = [
        ("PENDING", "Pending Review"),
        ("VERIFIED", "Verified"),
        ("REJECTED", "Rejected"),
    ]

    kyc_verification = models.ForeignKey(KYCVerification, on_delete=models.CASCADE, related_name="documents")
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPES)
    file = models.FileField(
        upload_to="kyc_documents/%Y/%m/",
        validators=[validate_document_extension, validate_document_size]
    )
    verification_status = models.CharField(max_length=20, choices=VERIFICATION_STATUS_CHOICES, default="PENDING")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="verified_kyc_documents"
    )
    reviewer_notes = models.TextField(blank=True, help_text="Reviewer comments")
    rejection_reason = models.TextField(blank=True, help_text="Why was this document rejected?")

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.get_document_type_display()} - {self.kyc_verification.customer.user.username}"


# ============================================================================
# ATM CARD REQUESTS
# ============================================================================

class ATMCardRequest(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("DELIVERED", "Delivered"),
        ("CANCELLED", "Cancelled"),
    ]

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="atm_card_requests")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    card_type = models.CharField(max_length=20, default="DEBIT", editable=False)
    masked_card_number = models.CharField(max_length=20, blank=True, help_text="XXXX-XXXX-XXXX-1234")
    expiry_date = models.DateField(null=True, blank=True, help_text="Card expiry (MM/YY)")
    delivery_address = models.TextField()
    requested_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_atm_cards"
    )
    delivered_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    def __str__(self):
        return f"ATM Card - {self.account.account_no} ({self.status})"

    # NOTE: no DB unique_together on (account, status) — that would block a
    # second REJECTED row for the same account. "One active request per
    # account" is enforced in helpers.check_atm_card_eligibility() instead.


# ============================================================================
# CHEQUE BOOK REQUESTS
# ============================================================================

class ChequebookRequest(models.Model):
    """
    Cheque book requests (savings/current accounts only).

    Flow: PENDING -> staff APPROVED (sets fee, but does NOT deduct it) ->
    customer pays fee themselves (own account or UPI) -> PROCESSING (order
    placed) -> DELIVERED. A zero fee skips the payment step and goes
    straight to PROCESSING on approval.
    """
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("APPROVED", "Approved - Fee Payment Required"),
        ("PROCESSING", "Processing (Fee Paid - Order Placed)"),
        ("REJECTED", "Rejected"),
        ("DELIVERED", "Delivered"),
        ("CANCELLED", "Cancelled"),
    ]

    LEAF_COUNT_CHOICES = [
        (25, "25 Leaves"),
        (50, "50 Leaves"),
        (100, "100 Leaves"),
    ]

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="cheque_requests")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    leaf_count = models.IntegerField(choices=LEAF_COUNT_CHOICES)
    delivery_address = models.TextField()
    cheque_book_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    fee_charged = models.BooleanField(default=False, help_text="Whether fee was deducted from account")
    requested_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_cheque_requests"
    )
    delivered_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-requested_at"]

    def __str__(self):
        return f"Cheque Request - {self.account.account_no} ({self.leaf_count} leaves, {self.status})"


# ============================================================================
# ACCOUNT STATEMENTS
# ============================================================================

class AccountStatement(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="statements")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    generated_at = models.DateTimeField(auto_now_add=True)
    transaction_count = models.IntegerField(default=0)
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    closing_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["-generated_at"]

    def __str__(self):
        return f"Statement {self.account.account_no} ({self.start_date} to {self.end_date})"