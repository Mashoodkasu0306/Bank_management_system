from users.models import Employee
from django.contrib.auth.models import User

DEFAULT_PRIORITY = {
    "TRANSACTION": "HIGH",
    "LOAN": "HIGH",
    "KYC": "MEDIUM",
    "ATM_CARD": "MEDIUM",
    "CHEQUE_BOOK": "MEDIUM",
    "STAFF_REQUEST": "MEDIUM",
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


def notify_staff(category, title, message, link="", priority=None,
                 related_type="", related_id=None):
    from .models import Notification
    employee_user_ids = Employee.objects.values_list("user_id", flat=True)
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