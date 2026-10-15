"""The customer's Recurring Payments pages. These pages only save the schedule:
money is moved by planning.recurring.run_due_payments()."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from audit.helpers import log_action
from audit.models import Actions
from services.freeze import frozen_block_response
from services.helpers import require_verified_kyc

from .models import RecurringPayment
from .recurring_forms import RecurringPaymentForm


@login_required
@require_GET
def my_recurring(request):
    customer = getattr(request.user, "customer", None)
    if customer is None:
        messages.error(request, "Only customers have recurring payments.")
        return redirect("home")

    payments = (
        RecurringPayment.objects.filter(customer=customer)
        .exclude(status=RecurringPayment.CANCELLED)
        .select_related("from_account", "to_account")
        .order_by("-created_at", "-id")
    )
    return render(request, "planning/recurring_list.html", {"payments": payments})


@login_required
@require_verified_kyc
@require_http_methods(["GET", "POST"])
def recurring_create(request):
    frozen = frozen_block_response(request, "recurring payments")
    if frozen:
        return frozen

    customer = request.user.customer
    form = RecurringPaymentForm(request.POST if request.method == "POST" else None, customer=customer)
    if request.method == "POST" and form.is_valid():
        payment = form.save()
        log_action(
            Actions.RECURRING_CREATED, request=request,
            target_type="RECURRING_PAYMENT", target_id=payment.id,
            details=(
                f"{payment.name}: {payment.amount} {payment.from_account.account_no} -> "
                f"{payment.to_account.account_no} ({payment.get_frequency_display()})"
            ),
        )
        messages.success(
            request, f"Recurring payment created. The first payment is on {payment.next_run_date}."
        )
        return redirect("my_recurring")
    return render(request, "planning/recurring_form.html", {"form": form})