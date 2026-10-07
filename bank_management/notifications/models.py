from django.db import models
from django.conf import settings


class Notification(models.Model):
    CATEGORY_CHOICES = [
        ("TRANSACTION", "Transaction"),
        ("KYC", "KYC"),
        ("ATM_CARD", "ATM Card"),
        ("CHEQUE_BOOK", "Cheque Book"),
        ("LOAN", "Loan"),
        ("STAFF_REQUEST", "Staff - Pending Request"),
        ("SUPPORT_CASE", "Support Case"),
    ]

    PRIORITY_CHOICES = [
        ("CRITICAL", "Critical"),
        ("HIGH", "High"),
        ("MEDIUM", "Medium"),
        ("LOW", "Low"),
    ]

    # Maps each category to the tab/group it belongs to in the Notification Center.
    CATEGORY_GROUP = {
        "TRANSACTION": "TRANSACTIONS",
        "LOAN": "BILLS_LOANS",
        "KYC": "SECURITY",
        "ATM_CARD": "SECURITY",
        "CHEQUE_BOOK": "SECURITY",
        "STAFF_REQUEST": "STAFF",
        "SUPPORT_CASE": "SUPPORT",
    }

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="MEDIUM")
    title = models.CharField(max_length=150)
    message = models.CharField(max_length=500)
    link = models.CharField(max_length=255, blank=True, help_text="URL path to navigate to on click")
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    # A "name tag" saying exactly which record this notification is about
    # (for example related_type="KYC", related_id=7). Old notifications have no tag.
    related_type = models.CharField(max_length=30, blank=True, default="")
    related_id = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.recipient.username} - {self.title}"

    def group(self):
        return self.CATEGORY_GROUP.get(self.category, "OTHER")