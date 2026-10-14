"""The staff page for running recurring payments. Money is moved only by run_due_payments()."""
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from transactions.views import is_admin_user

from .models import RecurringPayment
from .recurring import ENDED, ERROR, FAILED, PAID, PENDING, run_due_payments, summarize

RUN_LABELS = {
    PAID: "Paid", PENDING: "Sent for approval", FAILED: "Failed", ENDED: "Ended", ERROR: "Error",
}
PREVIEW_LABELS = {
    PAID: "Would pay", PENDING: "Would go to approval", FAILED: "Would fail",
    ENDED: "Would end", ERROR: "Would error",
}


def can_run_recurring(user):
    """Admins and employees of the Transactions department."""
    if not user.is_authenticated:
        return False
    if is_admin_user(user):
        return True
    employee = getattr(user, "employee", None)
    return employee is not None and employee.department == "TRANSACTIONS"


@login_required
@user_passes_test(can_run_recurring)
@require_http_methods(["GET", "POST"])
def run_recurring_page(request):
    ran = request.method == "POST"
    if ran:
        results = run_due_payments(run_by=request.user)
        labels = RUN_LABELS
    else:
        results = run_due_payments(dry_run=True)  # preview only: changes nothing
        labels = PREVIEW_LABELS

    for row in results:
        row["label"] = labels.get(row["outcome"], row["outcome"])

    return render(request, "planning/run_recurring.html", {
        "ran": ran,
        "results": results,
        "summary": summarize(results),
        "active_count": RecurringPayment.objects.filter(status=RecurringPayment.ACTIVE).count(),
        "paused_count": RecurringPayment.objects.filter(status=RecurringPayment.PAUSED).count(),
    })