from users.models import Employee
from django.contrib.auth.models import User

DEFAULT_PRIORITY = {
    "TRANSACTION": "HIGH",
    "LOAN": "HIGH",
    "KYC": "MEDIUM",
    "ATM_CARD": "MEDIUM",
    "CHEQUE_BOOK": "MEDIUM",
    "STAFF_REQUEST": "MEDIUM",
    "SUPPORT_CASE": "MEDIUM",
}


# Which department handles each kind of request.
# STAFF_REQUEST is left out on purpose: unless a department is named, only admins get it.
DEPARTMENT_FOR_CATEGORY = {
    "TRANSACTION": "TRANSACTIONS",
    "LOAN": "LOANS",
    "KYC": "KYC",
    "ATM_CARD": "CARDS_SERVICES",
    "CHEQUE_BOOK": "CARDS_SERVICES",
}


def notify(recipient_user, category, title, message, link="", priority=None,
           related_type="", related_id=None):
    from .models import Notification
    Notification.objects.create(
        recipient=recipient_user,
        category=category,
        priority=priority or DEFAULT_PRIORITY.get(category, "MEDIUM"),
        title=title,
        message=message,
        link=link,
        related_type=related_type,
        related_id=related_id,
    )


def notify_staff(category, title, message, link="", priority=None, department=None,
                 related_type="", related_id=None):
    from .models import Notification
    # Each category goes only to the department that handles it.
    # A department can also be named directly. Admins always get it.
    dept = department or DEPARTMENT_FOR_CATEGORY.get(category)
    if dept:
        employee_user_ids = Employee.objects.filter(department=dept).values_list("user_id", flat=True)
    else:
        employee_user_ids = []
    admin_users = User.objects.filter(is_superuser=True)

    recipients = set(employee_user_ids) | set(admin_users.values_list("id", flat=True))

    Notification.objects.bulk_create([
        Notification(
            recipient_id=uid, category=category,
            priority=priority or DEFAULT_PRIORITY.get(category, "MEDIUM"),
            title=title, message=message, link=link,
            related_type=related_type, related_id=related_id,
        )
        for uid in recipients
    ])


def notify_pending_transaction(txn):
    """Tell the Transactions department that a transaction is waiting for approval."""
    from django.urls import reverse
    account = txn.from_account or txn.to_account
    account_no = account.account_no if account else "-"
    message = (
        f"{txn.transaction_type.title()} of {txn.amount} on account {account_no} "
        f"needs approval. {txn.remarks}"
    )
    notify_staff(
        "TRANSACTION",
        "Transaction awaiting approval",
        message[:500],
        link=reverse("pending_transactions"),
        related_type="TRANSACTION",
        related_id=txn.id,
    )
