"""The customer's own Security Activity page, built from the audit log."""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import redirect, render
from django.utils import timezone

from audit.models import Actions, AuditLog

MAX_ROWS = 100

# action -> (what the customer reads, show in red, show the details, show the IP address)
FEED_TEXT = {
    Actions.LOGIN_SUCCESS: ("Signed in", False, False, True),
    Actions.LOGIN_FAILED: ("Failed sign-in attempt on your username", True, False, True),
    Actions.LOGOUT: ("Signed out", False, False, True),
    Actions.CARD_FROZEN: ("Card frozen", False, True, True),
    Actions.CARD_UNFROZEN: ("Card unfrozen", False, True, True),
    Actions.CARD_LIMIT_SET: ("Card limit changed", False, True, True),
    Actions.EMERGENCY_FREEZE: ("Emergency freeze started", True, True, True),
    # Done by staff: no staff name, note or address is shown to the customer.
    Actions.EMERGENCY_FREEZE_LIFTED: ("Emergency freeze lifted by the bank", False, False, False),
    Actions.TRANSFER_SENT: ("Transfer sent", False, True, True),
    Actions.STATEMENT_DOWNLOADED: ("Account statement downloaded", False, True, True),
    Actions.KYC_UPLOADED: ("KYC document uploaded", False, False, True),
    Actions.ATM_REQUESTED: ("ATM card requested", False, True, True),
    Actions.CHEQUE_REQUESTED: ("Cheque book requested", False, True, True),
    Actions.CHEQUE_FEE_PAID: ("Cheque book fee paid", False, True, True),
    Actions.LOAN_APPLIED: ("Loan application submitted", False, True, True),
    Actions.EMI_PAID: ("EMI paid", False, True, True),
    Actions.LUMP_SUM_PAID: ("Lump-sum payment made", False, True, True),
    Actions.FORECLOSURE_REQUESTED: ("Loan foreclosure requested", False, True, True),
}


def failed_logins_since(user, since):
    """Failed sign-ins that typed this user's username. They have no signed-in user."""
    return AuditLog.objects.filter(
        action=Actions.LOGIN_FAILED, actor__isnull=True,
        actor_username__iexact=user.username, created_at__gte=since,
    ).count()


def feed_for(customer, limit=MAX_ROWS):
    """The customer's own entries, newest first, as plain rows for the page."""
    user = customer.user
    wanted = (
        Q(actor=user)
        | Q(action=Actions.LOGIN_FAILED, actor__isnull=True, actor_username__iexact=user.username)
        | Q(action=Actions.EMERGENCY_FREEZE_LIFTED, target_type="CUSTOMER", target_id=customer.id)
    )
    entries = (
        AuditLog.objects.filter(wanted, action__in=list(FEED_TEXT))
        .order_by("-created_at", "-id")[:limit]
    )
    rows = []
    for entry in entries:
        label, warn, show_details, show_ip = FEED_TEXT[entry.action]
        rows.append({
            "when": entry.created_at,
            "label": label,
            "warn": warn,
            "details": entry.details if show_details else "",
            "ip": entry.ip_address if show_ip else None,
        })
    return rows


@login_required
def my_security_activity(request):
    customer = getattr(request.user, "customer", None)
    if customer is None:
        messages.error(request, "Only customers have a security activity page.")
        return redirect("home")

    from services.freeze import get_active_freeze

    logins = list(
        AuditLog.objects.filter(actor=request.user, action=Actions.LOGIN_SUCCESS)
        .order_by("-created_at", "-id")[:2]
    )
    # The newest sign-in is the one you are using now, so the one before it is the previous one.
    previous_login = logins[1] if len(logins) > 1 else None
    return render(request, "users/security_activity.html", {
        "rows": feed_for(customer),
        "previous_login": previous_login,
        "failed_week": failed_logins_since(request.user, timezone.now() - timedelta(days=7)),
        "freeze": get_active_freeze(customer),
    })
