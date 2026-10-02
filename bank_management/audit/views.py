from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from bank.views import is_admin
from users.models import Customer
from .helpers import log_action
from .models import AuditLog, Actions, SecurityAlert

MAX_ROWS = 200

# Things only a customer can do. Staff never see these in their own list.
CUSTOMER_ONLY_ACTIONS = (
    Actions.KYC_UPLOADED, Actions.ATM_REQUESTED, Actions.CHEQUE_REQUESTED,
    Actions.CHEQUE_FEE_PAID, Actions.LOAN_APPLIED, Actions.EMI_PAID,
    Actions.LUMP_SUM_PAID, Actions.FORECLOSURE_REQUESTED, Actions.TRANSFER_SENT,
)
STAFF_ACTIONS = tuple(a for a in Actions.ALL if a not in CUSTOMER_ONLY_ACTIONS)
# A statement can be downloaded by a customer or by staff, so it is in both lists.
CUSTOMER_ACTIONS = (
    (Actions.LOGIN_SUCCESS, Actions.LOGIN_FAILED, Actions.LOGOUT)
    + CUSTOMER_ONLY_ACTIONS
    + (Actions.STATEMENT_DOWNLOADED,)
)

USER_TYPES = (
    ("EMPLOYEE", "Employee (includes admin)"),
    ("CUSTOMER", "Customer"),
)


def _customer_q():
    """Entries made by a customer. A failed login has no signed-in user, so
    for those we match the typed username against the customers' usernames."""
    customer_usernames = Customer.objects.values_list("user__username", flat=True)
    return (
        Q(actor__customer__isnull=False)
        | Q(actor__isnull=True, actor_username__in=customer_usernames)
    )


def _staff_q():
    """Entries made by an employee or admin (anyone who is not a customer)."""
    staff_usernames = User.objects.filter(customer__isnull=True).values_list("username", flat=True)
    return (
        Q(actor__isnull=False, actor__customer__isnull=True)
        | Q(actor__isnull=True, actor_username__in=staff_usernames)
    )


@login_required
@user_passes_test(is_admin)
def audit_log_list(request):
    selected_type = request.GET.get("user_type", "").strip()
    if selected_type not in ("EMPLOYEE", "CUSTOMER"):
        selected_type = ""
    selected_action = request.GET.get("action", "").strip()
    username = request.GET.get("username", "").strip()

    action_map = {
        "": list(Actions.ALL),
        "EMPLOYEE": list(STAFF_ACTIONS),
        "CUSTOMER": list(CUSTOMER_ACTIONS),
    }
    allowed_actions = action_map[selected_type]
    if selected_action not in allowed_actions:
        selected_action = ""

    entries = AuditLog.objects.all()
    if selected_type == "CUSTOMER":
        entries = entries.filter(_customer_q())
    elif selected_type == "EMPLOYEE":
        entries = entries.filter(_staff_q())
    if selected_action:
        entries = entries.filter(action=selected_action)
    if username:
        # Matches the person who did it, OR a name mentioned in the details
        # (for example the customer a KYC document belonged to).
        entries = entries.filter(
            Q(actor_username__icontains=username) | Q(details__icontains=username)
        )

    total = entries.count()
    entries = entries[:MAX_ROWS]

    return render(request, "audit/audit_log.html", {
        "entries": entries,
        "total": total,
        "max_rows": MAX_ROWS,
        "user_types": USER_TYPES,
        "selected_user_type": selected_type,
        "actions": allowed_actions,
        "action_map": action_map,
        "selected_action": selected_action,
        "username": username,
    })


@login_required
@user_passes_test(is_admin)
def security_alerts(request):
    status = request.GET.get("status", "open").strip()
    if status not in ("open", "reviewed", "all"):
        status = "open"

    alerts = SecurityAlert.objects.select_related("reviewed_by")
    if status == "open":
        alerts = alerts.filter(is_reviewed=False)
    elif status == "reviewed":
        alerts = alerts.filter(is_reviewed=True)

    return render(request, "audit/security_alerts.html", {
        "alerts": alerts[:MAX_ROWS],
        "status": status,
        "open_count": SecurityAlert.objects.filter(is_reviewed=False).count(),
    })


@login_required
@user_passes_test(is_admin)
@require_POST
def review_alert(request, alert_id):
    alert = get_object_or_404(SecurityAlert, id=alert_id)

    if not alert.is_reviewed:
        alert.is_reviewed = True
        alert.reviewed_by = request.user
        alert.reviewed_at = timezone.now()
        alert.save()
        log_action(
            Actions.ALERT_REVIEWED, request=request,
            target_type="SECURITY_ALERT", target_id=alert.id,
            details=f"{alert.get_alert_type_display()}: {alert.subject}",
        )
        messages.success(request, "Alert marked as reviewed.")
    else:
        messages.error(request, "This alert was already reviewed.")

    return redirect("security_alerts")