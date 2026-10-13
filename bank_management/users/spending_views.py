"""The customer's own Spending Summary page. Read only."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from .spending import month_summary, parse_month


@login_required
@require_GET
def my_spending_summary(request):
    customer = getattr(request.user, "customer", None)
    if customer is None:
        messages.error(request, "Only customers have a spending summary.")
        return redirect("home")

    year, month = parse_month(request.GET.get("month"))
    return render(request, "users/spending_summary.html", {
        "s": month_summary(customer, year, month),
    })