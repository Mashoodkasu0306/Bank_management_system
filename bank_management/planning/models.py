from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models


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