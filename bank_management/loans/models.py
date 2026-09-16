from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from users.models import Customer
from accounts.models import Account


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


class LoanEligibilityRule(models.Model):
    """Admin-configurable eligibility thresholds per loan type.
    NOTE: 'income' here is a proxy derived from deposit history into the
    disbursement account - not a real payslip/bureau signal."""

    LOAN_TYPES = [
        ("HOME", "Home Loan"),
        ("PERSONAL", "Personal Loan"),
        ("CAR", "Car Loan"),
    ]

    loan_type = models.CharField(max_length=20, choices=LOAN_TYPES, unique=True)
    min_account_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("5000.00"))
    min_account_age_days = models.PositiveIntegerField(
        default=30,
        help_text="Minimum age of the ACCOUNT in days (not years). E.g. 365 = 1 year, 30 = 1 month."
    )
    max_debt_to_income_ratio = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("50.00"),
        help_text="Max % of income proxy that can go towards total EMI burden."
    )
    reference_annual_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("12.00"),
        help_text="Indicative rate used only to ESTIMATE EMI for the eligibility check at application time. The real rate is set by the approving employee."
    )

    def __str__(self):
        return f"Eligibility rule - {self.get_loan_type_display()}"


class Loan(models.Model):
    LOAN_TYPES = [
        ("HOME", "Home Loan"),
        ("PERSONAL", "Personal Loan"),
        ("CAR", "Car Loan"),
    ]
    REPAYMENT_TYPE_CHOICES = [
        ("EMI", "EMI (Fixed Monthly Installments)"),
        ("LUMP_SUM", "Lump Sum (Pay Any Amount, Any Time)"),
    ]
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("CLOSED", "Closed"),
        ("DEFAULTED", "Defaulted"),
        ("RENEWED", "Renewed"),
    ]
    FORECLOSURE_STATUS_CHOICES = [
        ("NONE", "None"),
        ("REQUESTED", "Requested"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="loans")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="loans")
    loan_type = models.CharField(max_length=20, choices=LOAN_TYPES)
    repayment_type = models.CharField(max_length=20, choices=REPAYMENT_TYPE_CHOICES, default="EMI")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    tenure_months = models.PositiveIntegerField()
    interest_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    emi_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    lump_sum_total_payable = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    lump_sum_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    applied_date = models.DateTimeField(auto_now_add=True)
    approved_date = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_loans"
    )
    remarks = models.CharField(max_length=255, blank=True)

    foreclosure_status = models.CharField(max_length=20, choices=FORECLOSURE_STATUS_CHOICES, default="NONE")
    foreclosure_requested_date = models.DateTimeField(null=True, blank=True)

    renewed_from = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="renewals"
    )
    renewal_fee = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    def __str__(self):
        return f"{self.get_loan_type_display()} - {self.customer.user.username} ({self.status})"

    def get_outstanding_principal(self):
        paid_principal = self.repayments.filter(status="PAID").aggregate(
            total=models.Sum("principal_component")
        )["total"] or Decimal("0.00")
        outstanding = self.amount - paid_principal
        return outstanding if outstanding > 0 else Decimal("0.00")

    def get_foreclosure_amount(self):
        """Returns (outstanding_principal, accrued_interest) for EMI loans - a
        pro-rated daily interest estimate since the last payment (or disbursement)."""
        outstanding_principal = self.get_outstanding_principal()

        if self.interest_rate is None:
            return outstanding_principal, Decimal("0.00")

        daily_rate = self.interest_rate / Decimal(100) / Decimal(365)
        last_payment = self.repayments.filter(status="PAID").order_by("-paid_date").first()

        if last_payment and last_payment.paid_date:
            reference_date = last_payment.paid_date.date()
        elif self.approved_date:
            reference_date = self.approved_date.date()
        else:
            reference_date = timezone.localdate()

        days_elapsed = max((timezone.localdate() - reference_date).days, 0)
        accrued_interest = (outstanding_principal * daily_rate * days_elapsed).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return outstanding_principal, accrued_interest

    def get_lump_sum_remaining(self):
        if self.lump_sum_total_payable is None:
            return Decimal("0.00")
        remaining = self.lump_sum_total_payable - self.lump_sum_paid
        return remaining if remaining > 0 else Decimal("0.00")

    def get_remaining_amount(self):
        """Unified 'how much is still owed' regardless of repayment type."""
        if self.repayment_type == "LUMP_SUM":
            return self.get_lump_sum_remaining()
        outstanding_principal, accrued_interest = self.get_foreclosure_amount()
        return outstanding_principal + accrued_interest

    def get_tenure_end_date(self):
        if not self.approved_date:
            return None
        return self.approved_date.date() + timedelta(days=30 * self.tenure_months)

    def is_fully_paid(self):
        if self.repayment_type == "LUMP_SUM":
            return self.lump_sum_total_payable is not None and self.lump_sum_paid >= self.lump_sum_total_payable
        return self.status == "APPROVED" and not self.repayments.filter(status="PENDING").exists()

    def refresh_default_status(self):
        """Lazily checks and flips status to DEFAULTED if the tenure window
        has passed with an outstanding balance. Called from views that display
        loan status, since this project has no background task scheduler."""
        if self.status != "APPROVED":
            return

        tenure_end = self.get_tenure_end_date()
        if tenure_end is None:
            return

        if timezone.localdate() > tenure_end and self.get_remaining_amount() > 0:
            self.status = "DEFAULTED"
            self.save(update_fields=["status"])

    def __str__(self):
        return f"{self.get_loan_type_display()} - {self.customer.user.username} ({self.status})"


class LoanRepayment(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("PAID", "Paid"),
        ("WAIVED", "Waived (Foreclosed)"),
    ]

    loan = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name="repayments")
    installment_number = models.PositiveIntegerField()
    due_date = models.DateField()
    emi_amount = models.DecimalField(max_digits=12, decimal_places=2)
    principal_component = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    interest_component = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    closing_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    paid_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["installment_number"]
        unique_together = ("loan", "installment_number")

    def __str__(self):
        return f"{self.loan} - Installment {self.installment_number}"

    def get_dpd_days(self):
        if self.status in ("PAID", "WAIVED"):
            return 0
        today = timezone.localdate()
        if self.due_date >= today:
            return 0
        return (today - self.due_date).days

    def get_dpd_bucket(self):
        dpd = self.get_dpd_days()
        if dpd <= 0:
            return "CURRENT"
        elif dpd <= 30:
            return "DPD 1-30"
        elif dpd <= 60:
            return "DPD 31-60"
        else:
            return "DPD 90+"


class LoanDocument(models.Model):
    DOCUMENT_TYPES = [
        ("ID_PROOF", "ID Proof"),
        ("INCOME_PROOF", "Income Proof"),
        ("ADDRESS_PROOF", "Address Proof"),
        ("OTHER", "Other"),
    ]

    loan = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name="documents")
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPES, default="OTHER")
    file = models.FileField(
        upload_to="loan_documents/%Y/%m/",
        validators=[validate_document_extension, validate_document_size],
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_document_type_display()} - Loan #{self.loan_id}"