from django.db import models
from django.conf import settings
from accounts.models import Account


class Transaction(models.Model):
    TRANSACTION_TYPES = [
        ("DEPOSIT", "Deposit"),
        ("WITHDRAW", "Withdraw"),
        ("TRANSFER", "Transfer"),
    ]
    MODE_CHOICES = [
        ("CASH", "Cash"),
        ("UPI", "UPI"),
        ("CARD", "Card"),
        ("NETBANKING", "Net Banking"),
    ]
    STATUS_CHOICES = [
        ("SUCCESS", "Success"),
        ("FAILED", "Failed"),
        ("PENDING", "Pending"),
    ]

    # What the money was spent on. Set by the customer. Loan payments are worked
    # out from is_loan_related, so they are not a choice here.
    CATEGORY_CHOICES = [
        ("FOOD", "Food"),
        ("SHOPPING", "Shopping"),
        ("BILLS", "Bills"),
        ("RENT", "Rent"),
        ("TRAVEL", "Travel"),
        ("HEALTH", "Health"),
        ("EDUCATION", "Education"),
        ("ENTERTAINMENT", "Entertainment"),
        ("SAVINGS", "Savings"),
        ("OTHER", "Other"),
    ]
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES)
    from_account = models.ForeignKey(
        Account, on_delete=models.CASCADE,
        related_name="outgoing_transactions",
        null=True, blank=True
    )
    to_account = models.ForeignKey(
        Account, on_delete=models.CASCADE,
        related_name="incoming_transactions",
        null=True, blank=True
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    mode_of_transaction = models.CharField(max_length=20, choices=MODE_CHOICES, default="CASH")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    remarks = models.CharField(max_length=255, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    is_loan_related = models.BooleanField(default=False)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="OTHER")

    def __str__(self):
        return f"{self.transaction_type} - {self.amount} ({self.status})"