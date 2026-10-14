from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from transactions.models import Transaction


class SavingsGoal(models.Model):
    """A target the customer is saving towards. Tracking only: the linked account's
    balance is the one source of truth, and a goal never moves or reserves money."""

    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    STATUS_CHOICES = [
        (ACTIVE, "Active"),
        (ARCHIVED, "Archived"),
    ]

    customer = models.ForeignKey(
        "users.Customer", on_delete=models.CASCADE, related_name="savings_goals"
    )
    account = models.ForeignKey(
        "accounts.Account", on_delete=models.CASCADE, related_name="savings_goals"
    )
    name = models.CharField(max_length=80)
    target_amount = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    target_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if not self.account_id:
            return
        account = self.account
        if self.customer_id and account.customer_id != self.customer_id:
            raise ValidationError({"account": "You can only set a goal on your own account."})
        if account.account_type not in ("SAVINGS", "CURRENT"):
            raise ValidationError({"account": "Goals can only be set on a savings or current account."})

    def __str__(self):
        return f"{self.name} ({self.target_amount})"


class RecurringPayment(models.Model):
    """A repeating transfer set up by a customer. This model only holds the schedule:
    money is moved only by planning.recurring.run_due_payments()."""

    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    FREQUENCY_CHOICES = [
        (WEEKLY, "Weekly"),
        (MONTHLY, "Monthly"),
    ]

    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"
    STATUS_CHOICES = [
        (ACTIVE, "Active"),
        (PAUSED, "Paused"),
        (ENDED, "Ended"),
        (CANCELLED, "Cancelled"),
    ]

    customer = models.ForeignKey(
        "users.Customer", on_delete=models.CASCADE, related_name="recurring_payments"
    )
    from_account = models.ForeignKey(
        "accounts.Account", on_delete=models.CASCADE, related_name="recurring_payments_out"
    )
    to_account = models.ForeignKey(
        "accounts.Account", on_delete=models.CASCADE, related_name="recurring_payments_in"
    )
    name = models.CharField(max_length=80)
    amount = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    category = models.CharField(max_length=20, choices=Transaction.CATEGORY_CHOICES, default="OTHER")
    frequency = models.CharField(max_length=10, choices=FREQUENCY_CHOICES, default=MONTHLY)
    next_run_date = models.DateField()
    # The day of the month a monthly payment belongs to, so the 31st comes back after a short month.
    anchor_day = models.PositiveSmallIntegerField(null=True, blank=True, editable=False)
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=ACTIVE)
    consecutive_failures = models.PositiveSmallIntegerField(default=0, editable=False)
    last_run_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_result = models.CharField(max_length=200, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["status", "next_run_date"])]

    def set_start(self, start_date):
        self.next_run_date = start_date
        self.anchor_day = start_date.day

    def clean(self):
        errors = {}
        if self.from_account_id:
            source = self.from_account
            if self.customer_id and source.customer_id != self.customer_id:
                errors["from_account"] = "You can only pay from your own account."
            elif source.account_type not in ("SAVINGS", "CURRENT"):
                errors["from_account"] = "Payments can only be made from a savings or current account."
        if self.from_account_id and self.from_account_id == self.to_account_id:
            errors["to_account"] = "The destination must be a different account."
        if self.end_date and self.next_run_date and self.end_date < self.next_run_date:
            errors["end_date"] = "The end date cannot be before the first payment date."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.name} ({self.amount} {self.get_frequency_display()})"