from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.models import Account
from transactions.models import Transaction
from users.models import Customer


class SupportCase(models.Model):
    """One dispute or complaint. It is a record plus a decision.
    Staff accept or reject it with a written answer. No money moves from here."""

    DISPUTE = "DISPUTE"
    COMPLAINT = "COMPLAINT"
    TYPE_CHOICES = [
        (DISPUTE, "Dispute"),
        (COMPLAINT, "Complaint"),
    ]

    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    STATUS_CHOICES = [
        (OPEN, "Open"),
        (IN_REVIEW, "In review"),
        (ACCEPTED, "Accepted"),
        (REJECTED, "Rejected"),
    ]
    OPEN_STATUSES = (OPEN, IN_REVIEW)

    CATEGORY_CHOICES = [
        ("UNAUTHORISED", "I did not make this transaction"),
        ("DUPLICATE", "Charged twice"),
        ("WRONG_AMOUNT", "Wrong amount"),
        ("SERVICE", "Branch or service problem"),
        ("CARD", "Card problem"),
        ("LOAN", "Loan problem"),
        ("OTHER", "Something else"),
    ]

    # Days the bank has to answer, by type.
    DEADLINE_DAYS = {DISPUTE: 10, COMPLAINT: 7}

    case_type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="support_cases")
    account = models.ForeignKey(
        Account, on_delete=models.SET_NULL, null=True, blank=True, related_name="support_cases"
    )
    transaction = models.ForeignKey(
        Transaction, on_delete=models.SET_NULL, null=True, blank=True, related_name="support_cases"
    )
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="OTHER")
    subject = models.CharField(max_length=150)
    description = models.TextField()

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=OPEN, db_index=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="assigned_cases",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    due_at = models.DateTimeField(null=True, blank=True)

    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="decided_cases",
    )
    decision_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.reference} {self.subject}"

    def save(self, *args, **kwargs):
        if self._state.adding and not self.due_at:
            days = self.DEADLINE_DAYS.get(self.case_type, 7)
            self.due_at = timezone.now() + timedelta(days=days)
        super().save(*args, **kwargs)

    @property
    def reference(self):
        return f"CASE-{self.pk:06d}" if self.pk else "CASE-NEW"

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES

    @property
    def is_overdue(self):
        return bool(self.is_open and self.due_at and timezone.now() > self.due_at)


class SupportMessage(models.Model):
    """A reply on a case, from the customer or from staff."""

    case = models.ForeignKey(SupportCase, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="support_messages",
    )
    from_staff = models.BooleanField(default=False)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.case.reference} message {self.pk}"