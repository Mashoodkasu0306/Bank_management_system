from django.conf import settings
from django.db import models


class Actions:
    """The names of the things we record. Adding a new one later needs no migration."""
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    EMPLOYEE_DEPARTMENT_CHANGED = "EMPLOYEE_DEPARTMENT_CHANGED"
    CARD_FROZEN = "CARD_FROZEN"
    CARD_UNFROZEN = "CARD_UNFROZEN"
    CARD_LIMIT_SET = "CARD_LIMIT_SET"
    EMERGENCY_FREEZE = "EMERGENCY_FREEZE"
    EMERGENCY_FREEZE_LIFTED = "EMERGENCY_FREEZE_LIFTED"

    KYC_VERIFIED = "KYC_VERIFIED"
    KYC_REJECTED = "KYC_REJECTED"
    ATM_APPROVED = "ATM_APPROVED"
    ATM_REJECTED = "ATM_REJECTED"
    CHEQUE_APPROVED = "CHEQUE_APPROVED"
    CHEQUE_REJECTED = "CHEQUE_REJECTED"

    TXN_APPROVED = "TXN_APPROVED"
    TXN_REJECTED = "TXN_REJECTED"

    LOAN_APPROVED = "LOAN_APPROVED"
    LOAN_REJECTED = "LOAN_REJECTED"
    LOAN_RENEWED = "LOAN_RENEWED"
    FORECLOSURE_APPROVED = "FORECLOSURE_APPROVED"
    FORECLOSURE_REJECTED = "FORECLOSURE_REJECTED"

    CUSTOMER_REGISTERED = "CUSTOMER_REGISTERED"
    CUSTOMER_UPDATED = "CUSTOMER_UPDATED"
    CUSTOMER_DEACTIVATED = "CUSTOMER_DEACTIVATED"
    CUSTOMER_ACTIVATED = "CUSTOMER_ACTIVATED"

    # Things a customer does themselves
    KYC_UPLOADED = "KYC_UPLOADED"
    ATM_REQUESTED = "ATM_REQUESTED"
    CHEQUE_REQUESTED = "CHEQUE_REQUESTED"
    CHEQUE_FEE_PAID = "CHEQUE_FEE_PAID"
    STATEMENT_DOWNLOADED = "STATEMENT_DOWNLOADED"
    LOAN_APPLIED = "LOAN_APPLIED"
    EMI_PAID = "EMI_PAID"
    LUMP_SUM_PAID = "LUMP_SUM_PAID"
    FORECLOSURE_REQUESTED = "FORECLOSURE_REQUESTED"
    TRANSFER_SENT = "TRANSFER_SENT"

    # An admin looked at a security alert
    ALERT_REVIEWED = "ALERT_REVIEWED"

    # An admin or employee downloaded a report
    REPORT_EXPORTED = "REPORT_EXPORTED"

    ALL = (
        LOGIN_SUCCESS, LOGIN_FAILED, LOGOUT,
        KYC_VERIFIED, KYC_REJECTED, ATM_APPROVED, ATM_REJECTED,
        CHEQUE_APPROVED, CHEQUE_REJECTED, TXN_APPROVED, TXN_REJECTED,
        LOAN_APPROVED, LOAN_REJECTED, LOAN_RENEWED,
        FORECLOSURE_APPROVED, FORECLOSURE_REJECTED,
        CUSTOMER_REGISTERED, CUSTOMER_UPDATED,
        CUSTOMER_DEACTIVATED, CUSTOMER_ACTIVATED,
        KYC_UPLOADED, ATM_REQUESTED, CHEQUE_REQUESTED, CHEQUE_FEE_PAID,
        STATEMENT_DOWNLOADED, LOAN_APPLIED, EMI_PAID, LUMP_SUM_PAID,
        FORECLOSURE_REQUESTED, TRANSFER_SENT,
        ALERT_REVIEWED, REPORT_EXPORTED,
        EMPLOYEE_DEPARTMENT_CHANGED,
        CARD_FROZEN, CARD_UNFROZEN, CARD_LIMIT_SET,
        EMERGENCY_FREEZE, EMERGENCY_FREEZE_LIFTED,
    )


class AuditLog(models.Model):
    """One line in the notebook: who did what, to which record, from where, and when.
    Lines can be added but never changed or removed through the normal code."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="audit_entries",
    )
    # Kept as plain text too, so the line still makes sense if the user is deleted,
    # and so a failed login can record the username that was tried.
    actor_username = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=40, db_index=True)
    target_type = models.CharField(max_length=30, blank=True)
    target_id = models.PositiveIntegerField(null=True, blank=True)
    details = models.CharField(max_length=500, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        who = self.actor_username or "unknown"
        return f"{self.created_at:%Y-%m-%d %H:%M} {who} {self.action}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError("Audit log entries cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Audit log entries cannot be deleted.")


class SecurityAlert(models.Model):
    """A warning raised automatically when something looks unusual.
    An admin reviews it and marks it as reviewed."""

    FAILED_LOGINS = "FAILED_LOGINS"
    LARGE_TRANSFER = "LARGE_TRANSFER"
    TYPE_CHOICES = [
        (FAILED_LOGINS, "Many failed logins"),
        (LARGE_TRANSFER, "Unusually large transfer"),
    ]

    alert_type = models.CharField(max_length=30, choices=TYPE_CHOICES, db_index=True)
    subject = models.CharField(max_length=150)  # a username, or an account number
    message = models.CharField(max_length=500)
    target_type = models.CharField(max_length=30, blank=True)
    target_id = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    is_reviewed = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="reviewed_alerts",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.get_alert_type_display()} - {self.subject}"