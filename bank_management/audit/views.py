from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render

from bank.views import is_admin
from .models import AuditLog, Actions

MAX_ROWS = 200


@login_required
@user_passes_test(is_admin)
def audit_log_list(request):
    selected_action = request.GET.get("action", "").strip()
    username = request.GET.get("username", "").strip()

    entries = AuditLog.objects.all()
    if selected_action in Actions.ALL:
        entries = entries.filter(action=selected_action)
    if username:
        entries = entries.filter(actor_username__icontains=username)

    total = entries.count()
    entries = entries[:MAX_ROWS]

    return render(request, "audit/audit_log.html", {
        "entries": entries,
        "total": total,
        "max_rows": MAX_ROWS,
        "actions": Actions.ALL,
        "selected_action": selected_action,
        "username": username,
    })