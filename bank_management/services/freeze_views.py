"""Staff side of the emergency freeze: see frozen customers and lift a freeze."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from audit.helpers import log_action
from audit.models import Actions
from bank.views import is_admin
from notifications.helpers import notify
from notifications.models import Notification
from users.models import Employee

from .freeze import EMERGENCY, lift_emergency_freeze
from .models import ATMCardRequest, EmergencyFreeze


def can_manage_freezes(user):
    """Admins and Customer Support employees may see and lift emergency freezes."""
    if not user.is_authenticated:
        return False
    return is_admin(user) or Employee.objects.filter(user=user, department="SUPPORT").exists()


@login_required
@user_passes_test(can_manage_freezes)
def frozen_customers(request):
    active = list(
        EmergencyFreeze.objects.filter(lifted_at__isnull=True)
        .select_related("customer__user").order_by("started_at")
    )
    for freeze in active:
        freeze.cards_frozen = ATMCardRequest.objects.filter(
            account__customer=freeze.customer, freeze_state=EMERGENCY
        ).count()
    lifted = (
        EmergencyFreeze.objects.filter(lifted_at__isnull=False)
        .select_related("customer__user", "lifted_by").order_by("-lifted_at")[:10]
    )
    return render(request, "services/staff/frozen_customers.html", {
        "active": active, "lifted": lifted,
    })


@login_required
@user_passes_test(can_manage_freezes)
@require_POST
def lift_freeze(request, freeze_id):
    freeze = get_object_or_404(EmergencyFreeze.objects.select_related("customer__user"), id=freeze_id)
    note = request.POST.get("note", "").strip()
    if not note:
        messages.error(request, "Please write how the customer's identity was confirmed.")
        return redirect("frozen_customers")

    username = freeze.customer.user.username
    if lift_emergency_freeze(freeze, request.user, note):
        log_action(
            Actions.EMERGENCY_FREEZE_LIFTED, request=request,
            target_type="CUSTOMER", target_id=freeze.customer_id,
            details=f"{username}: {note}"[:500],
        )
        Notification.objects.filter(
            related_type="FREEZE", related_id=freeze.id, is_read=False
        ).update(is_read=True)
        notify(
            freeze.customer.user, "ATM_CARD", "Emergency freeze lifted",
            "The bank has lifted your emergency freeze. Your cards and online transfers work again. "
            "Cards you froze yourself stay frozen until you unfreeze them.",
            link=reverse("card_controls"),
        )
        messages.success(request, f"Freeze lifted for {username}.")
    else:
        messages.info(request, f"The freeze for {username} was already lifted.")
    return redirect("frozen_customers")
