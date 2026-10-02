from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db.models import Avg
from django.utils import timezone

from .models import Actions, AuditLog, SecurityAlert

# ---- The rules. Change a number here to make the alerts more or less sensitive. ----
FAILED_LOGIN_LIMIT = 5              # this many failed logins ...
FAILED_LOGIN_WINDOW_MINUTES = 15    # ... within this many minutes raises an alert

LARGE_TRANSFER_MULTIPLIER = 5       # alert when a transfer is MORE than 5x the usual amount
LARGE_TRANSFER_MIN_HISTORY = 3      # needs at least this many earlier transfers to judge
LARGE_TRANSFER_HISTORY_DAYS = 90    # "earlier transfers" means the last 90 days
# Optional: set a number such as Decimal("50000.00") to ALWAYS alert on transfers
# at or above it, even for accounts with no history. None means switched off.
LARGE_TRANSFER_FIXED_LIMIT = None


def _tell_admins(title, message):
    from notifications.helpers import notify  # imported here to avoid a circular import
    for admin in User.objects.filter(is_superuser=True, is_active=True):
        notify(admin, "STAFF_REQUEST", title, message[:500],
               link="/audit/alerts/", priority="HIGH")


def check_failed_logins(username):
    """Call right after a failed login is written to the audit log."""
    username = (username or "").strip()
    if not username:
        return None

    since = timezone.now() - timedelta(minutes=FAILED_LOGIN_WINDOW_MINUTES)
    attempts = AuditLog.objects.filter(
        action=Actions.LOGIN_FAILED,
        actor_username__iexact=username,
        created_at__gte=since,
    ).count()
    if attempts < FAILED_LOGIN_LIMIT:
        return None

    # Already warned about this username in this time window? Do not repeat.
    already_warned = SecurityAlert.objects.filter(
        alert_type=SecurityAlert.FAILED_LOGINS,
        subject__iexact=username,
        created_at__gte=since,
    ).exists()
    if already_warned:
        return None

    message = (
        f"{attempts} failed login attempts for username '{username}' "
        f"in the last {FAILED_LOGIN_WINDOW_MINUTES} minutes."
    )
    alert = SecurityAlert.objects.create(
        alert_type=SecurityAlert.FAILED_LOGINS,
        subject=username[:150],
        message=message[:500],
    )
    _tell_admins("Security alert: many failed logins", message)
    return alert


def check_large_transfer(from_account, amount):
    """Call right after a successful transfer. The newest successful transfer from
    this account is treated as "this one", and the older ones are the history."""
    from transactions.models import Transaction

    amount = Decimal(amount)
    sent = Transaction.objects.filter(
        from_account=from_account, transaction_type="TRANSFER", status="SUCCESS",
    ).order_by("-id")
    current = sent.first()
    if current is None:
        return None

    since = timezone.now() - timedelta(days=LARGE_TRANSFER_HISTORY_DAYS)
    history = sent.exclude(id=current.id).filter(timestamp__gte=since)

    reason = None
    if LARGE_TRANSFER_FIXED_LIMIT is not None and amount >= LARGE_TRANSFER_FIXED_LIMIT:
        reason = f"at or above the fixed limit of {LARGE_TRANSFER_FIXED_LIMIT}"
    elif history.count() >= LARGE_TRANSFER_MIN_HISTORY:
        average = history.aggregate(avg=Avg("amount"))["avg"]
        if average is not None:
            average = Decimal(str(average))
            if average > 0 and amount > average * LARGE_TRANSFER_MULTIPLIER:
                reason = f"more than {LARGE_TRANSFER_MULTIPLIER}x the usual amount of {average:.2f}"

    if reason is None:
        return None

    owner = from_account.customer.user.username
    message = f"Transfer of {amount} from account {from_account.account_no} ({owner}) is {reason}."
    alert = SecurityAlert.objects.create(
        alert_type=SecurityAlert.LARGE_TRANSFER,
        subject=from_account.account_no,
        message=message[:500],
        target_type="TRANSACTION",
        target_id=current.id,
    )
    _tell_admins("Security alert: unusually large transfer", message)
    return alert