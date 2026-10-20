from datetime import timedelta

from django.utils import timezone

from .alerts import FAILED_LOGIN_LIMIT, FAILED_LOGIN_WINDOW_MINUTES
from .models import Actions, AuditLog

LOCKOUT_MINUTES = FAILED_LOGIN_WINDOW_MINUTES


def is_locked_out(username):
    """True when this username has too many recent failed logins.

    It uses the same numbers as the security alert (audit/alerts.py). Only
    failures AFTER the last successful login count, so a good login resets it.
    The answer is the same whether or not the username exists.
    """
    username = (username or "").strip()
    if not username:
        return False

    since = timezone.now() - timedelta(minutes=FAILED_LOGIN_WINDOW_MINUTES)
    last_ok = (
        AuditLog.objects.filter(
            action=Actions.LOGIN_SUCCESS,
            actor__username__iexact=username,
            created_at__gte=since,
        )
        .order_by("-created_at")
        .first()
    )
    if last_ok is not None:
        since = last_ok.created_at

    failures = AuditLog.objects.filter(
        action=Actions.LOGIN_FAILED,
        actor_username__iexact=username,
        created_at__gt=since,
    ).count()
    return failures >= FAILED_LOGIN_LIMIT
