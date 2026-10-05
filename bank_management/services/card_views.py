"""Customer card controls: freeze, unfreeze, daily card limit, and the emergency button."""
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from audit.helpers import log_action
from audit.models import Actions
from notifications.helpers import notify, notify_staff

from .freeze import CUSTOMER, emergency_freeze, get_active_freeze, live_cards

STAFF_FREEZE_LIST = "/services/staff/frozen-customers/"


def _customer(request):
    return getattr(request.user, "customer", None)


def _label(card):
    return card.masked_card_number or f"card #{card.id}"


def _guard(request, card_id):
    """Shared checks for freeze and limit changes. Returns (card, redirect_response)."""
    customer = _customer(request)
    if customer is None:
        messages.error(request, "Only customers can manage cards.")
        return None, redirect("customer_dashboard")
    card = live_cards(customer).filter(id=card_id).first()
    if card is None:
        messages.error(request, "Card not found.")
        return None, redirect("card_controls")
    if get_active_freeze(customer):
        messages.error(request, "An emergency freeze is on. Cards can be changed after the bank lifts it.")
        return None, redirect("card_controls")
    return card, None


@login_required
def card_controls(request):
    customer = _customer(request)
    if customer is None:
        messages.error(request, "Only customers can manage cards.")
        return redirect("customer_dashboard")
    return render(request, "services/card_controls.html", {
        "cards": live_cards(customer),
        "freeze": get_active_freeze(customer),
    })


@login_required
@require_POST
def card_freeze_toggle(request, card_id):
    card, stop = _guard(request, card_id)
    if stop:
        return stop

    action = request.POST.get("action")
    if action == "freeze" and card.freeze_state == "":
        card.freeze_state = CUSTOMER
        card.save(update_fields=["freeze_state"])
        log_action(
            Actions.CARD_FROZEN, request=request,
            target_type="ATM_CARD_REQUEST", target_id=card.id,
            details=f"{_label(card)} on account {card.account.account_no}",
        )
        messages.success(request, f"Card {_label(card)} is frozen.")
    elif action == "unfreeze" and card.freeze_state == CUSTOMER:
        card.freeze_state = ""
        card.save(update_fields=["freeze_state"])
        log_action(
            Actions.CARD_UNFROZEN, request=request,
            target_type="ATM_CARD_REQUEST", target_id=card.id,
            details=f"{_label(card)} on account {card.account.account_no}",
        )
        messages.success(request, f"Card {_label(card)} is active again.")
    else:
        messages.error(request, "Nothing to change.")
    return redirect("card_controls")


@login_required
@require_POST
def card_set_limit(request, card_id):
    card, stop = _guard(request, card_id)
    if stop:
        return stop

    raw = request.POST.get("limit", "").strip()
    if raw == "":
        new_limit = None
    else:
        try:
            new_limit = Decimal(raw)
        except InvalidOperation:
            messages.error(request, "Enter a valid amount.")
            return redirect("card_controls")
        if not new_limit.is_finite() or new_limit <= 0:
            messages.error(request, "The limit must be greater than zero.")
            return redirect("card_controls")
        if new_limit > card.account.daily_limit:
            messages.error(
                request,
                f"The card limit cannot be more than the account's daily limit ({card.account.daily_limit}).",
            )
            return redirect("card_controls")
        new_limit = new_limit.quantize(Decimal("0.01"))

    card.card_daily_limit = new_limit
    card.save(update_fields=["card_daily_limit"])
    shown = "removed" if new_limit is None else str(new_limit)
    log_action(
        Actions.CARD_LIMIT_SET, request=request,
        target_type="ATM_CARD_REQUEST", target_id=card.id,
        details=f"{_label(card)}: limit {shown}",
    )
    messages.success(request, "Card limit removed." if new_limit is None else f"Card limit set to {new_limit}.")
    return redirect("card_controls")


@login_required
@require_POST
def emergency_freeze_start(request):
    customer = _customer(request)
    if customer is None:
        messages.error(request, "Only customers can use the emergency freeze.")
        return redirect("customer_dashboard")

    freeze, frozen_count = emergency_freeze(customer)
    if freeze is None:
        messages.info(request, "An emergency freeze is already on.")
        return redirect("card_controls")

    username = request.user.username
    log_action(
        Actions.EMERGENCY_FREEZE, request=request,
        target_type="CUSTOMER", target_id=customer.id,
        details=f"{frozen_count} card(s) frozen; online transfers blocked",
    )
    notify(
        request.user, "ATM_CARD", "Emergency freeze is on",
        "All your cards are frozen and online transfers are blocked. "
        "Contact the bank to lift the freeze.",
        link=reverse("card_controls"), priority="CRITICAL",
    )
    notify_staff(
        "ATM_CARD", f"Emergency freeze: {username}",
        f"{username} froze {frozen_count} card(s) and blocked online transfers. "
        "Verify the customer before lifting it.",
        link=STAFF_FREEZE_LIST, priority="CRITICAL", department="SUPPORT",
        related_type="FREEZE", related_id=freeze.id,
    )
    messages.success(request, "Emergency freeze is on. Contact the bank to lift it.")
    return redirect("card_controls")
