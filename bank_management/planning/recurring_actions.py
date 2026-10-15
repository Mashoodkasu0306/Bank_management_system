"""Pause, resume and cancel for a customer's own recurring payments.
These only change the schedule's status: they never move money."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction as db_transaction
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from audit.helpers import log_action
from audit.models import Actions

from .models import RecurringPayment
from .recurring import move_to_future


def _audit(request, action, payment, note=""):
    log_action(
        action, request=request,
        target_type="RECURRING_PAYMENT", target_id=payment.id,
        details=(
            f"{payment.name}: {payment.amount} {payment.from_account.account_no} -> "
            f"{payment.to_account.account_no}{note}"
        ),
    )


def _customer_or_redirect(request):
    customer = getattr(request.user, "customer", None)
    if customer is None:
        messages.error(request, "Only customers have recurring payments.")
    return customer


@login_required
@require_POST
def recurring_pause(request, payment_id):
    customer = _customer_or_redirect(request)
    if customer is None:
        return redirect("home")

    with db_transaction.atomic():
        payment = get_object_or_404(
            RecurringPayment.objects.select_for_update(), id=payment_id, customer=customer
        )
        if payment.status != RecurringPayment.ACTIVE:
            messages.error(request, "Only an active payment can be paused.")
            return redirect("my_recurring")
        payment.status = RecurringPayment.PAUSED
        payment.save(update_fields=["status", "updated_at"])

    _audit(request, Actions.RECURRING_PAUSED, payment)
    messages.success(request, f"{payment.name} is paused. No payments will be made until you resume it.")
    return redirect("my_recurring")


@login_required
@require_POST
def recurring_resume(request, payment_id):
    customer = _customer_or_redirect(request)
    if customer is None:
        return redirect("home")

    today = timezone.localdate()
    with db_transaction.atomic():
        payment = get_object_or_404(
            RecurringPayment.objects.select_for_update(), id=payment_id, customer=customer
        )
        if payment.status != RecurringPayment.PAUSED:
            messages.error(request, "Only a paused payment can be resumed.")
            return redirect("my_recurring")

        payment.consecutive_failures = 0
        move_to_future(payment, today)  # never a surprise payment today
        ended = bool(payment.end_date and payment.next_run_date > payment.end_date)
        payment.status = RecurringPayment.ENDED if ended else RecurringPayment.ACTIVE
        payment.save(update_fields=["status", "consecutive_failures", "next_run_date", "updated_at"])

    if ended:
        _audit(request, Actions.RECURRING_RESUMED, payment, note=" (ended: past its last payment date)")
        messages.error(request, f"{payment.name} has passed its last payment date, so it has ended.")
    else:
        _audit(request, Actions.RECURRING_RESUMED, payment)
        messages.success(request, f"{payment.name} is active again. The next payment is on {payment.next_run_date}.")
    return redirect("my_recurring")


@login_required
@require_POST
def recurring_cancel(request, payment_id):
    customer = _customer_or_redirect(request)
    if customer is None:
        return redirect("home")

    with db_transaction.atomic():
        payment = get_object_or_404(
            RecurringPayment.objects.select_for_update(), id=payment_id, customer=customer
        )
        if payment.status not in (RecurringPayment.ACTIVE, RecurringPayment.PAUSED):
            messages.error(request, "This payment cannot be cancelled.")
            return redirect("my_recurring")
        payment.status = RecurringPayment.CANCELLED
        payment.save(update_fields=["status", "updated_at"])

    _audit(request, Actions.RECURRING_CANCELLED, payment)
    messages.success(request, f"{payment.name} was cancelled.")
    return redirect("my_recurring")