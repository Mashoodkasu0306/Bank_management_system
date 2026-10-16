"""The customer's Money Insights page. Read only: nothing here changes data."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from .insights import build_insights


@login_required
@require_GET
def my_insights(request):
    customer = getattr(request.user, "customer", None)
    if customer is None:
        messages.error(request, "Only customers have a money insights page.")
        return redirect("home")
    return render(request, "planning/insights.html", {"i": build_insights(customer)})