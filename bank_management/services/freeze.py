"""Card freeze and emergency freeze rules. The views only call these functions."""
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import ATMCardRequest, EmergencyFreeze

LIVE_STATUSES = ("APPROVED", "DELIVERED")  # a real card exists only after approval
CUSTOMER = "CUSTOMER"
EMERGENCY = "EMERGENCY"


def customer_has_active_freeze(customer):
    return EmergencyFreeze.objects.filter(customer=customer, lifted_at__isnull=True).exists()


def get_active_freeze(customer):
    return EmergencyFreeze.objects.filter(customer=customer, lifted_at__isnull=True).first()


def live_cards(customer):
    return ATMCardRequest.objects.filter(
        account__customer=customer, status__in=LIVE_STATUSES
    ).select_related("account").order_by("account__account_no", "id")


def emergency_freeze(customer):
    """Freeze all live cards and start a freeze record.

    Returns (freeze, number_of_cards_frozen), or (None, 0) if a freeze is already active.
    Cards the customer froze themselves are left as they are.
    """
    try:
        with transaction.atomic():
            already = EmergencyFreeze.objects.select_for_update().filter(
                customer=customer, lifted_at__isnull=True
            ).exists()
            if already:
                return None, 0
            freeze = EmergencyFreeze.objects.create(customer=customer)
            frozen = ATMCardRequest.objects.filter(
                account__customer=customer, status__in=LIVE_STATUSES, freeze_state=""
            ).update(freeze_state=EMERGENCY)
            return freeze, frozen
    except IntegrityError:
        return None, 0


def lift_emergency_freeze(freeze, staff_user, note):
    """End a freeze and unfreeze the cards it froze.

    Cards the customer froze themselves stay frozen.
    Returns False if the freeze was already lifted.
    """
    with transaction.atomic():
        freeze = EmergencyFreeze.objects.select_for_update().get(pk=freeze.pk)
        if freeze.lifted_at is not None:
            return False
        freeze.lifted_at = timezone.now()
        freeze.lifted_by = staff_user
        freeze.lift_note = note[:300]
        freeze.save(update_fields=["lifted_at", "lifted_by", "lift_note"])
        ATMCardRequest.objects.filter(
            account__customer=freeze.customer, freeze_state=EMERGENCY
        ).update(freeze_state="")
        return True


def frozen_block_response(request, what="online payments"):
    """If the logged-in customer is under an emergency freeze, return a redirect with an
    error message. Otherwise return None, so the view carries on."""
    from django.contrib import messages
    from django.shortcuts import redirect

    customer = getattr(request.user, "customer", None)
    if customer is None or not customer_has_active_freeze(customer):
        return None
    messages.error(
        request,
        f"Your account is under an emergency freeze, so {what} are blocked. "
        "Please contact the bank to lift it.",
    )
    return redirect("customer_dashboard")
