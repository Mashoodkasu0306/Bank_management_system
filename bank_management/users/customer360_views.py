"""The Customer 360 page: one read-only screen with everything about a customer."""
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from audit.helpers import log_action
from audit.models import Actions
from bank.views import is_admin_or_employee
from support.staff_views import can_manage_cases

from .customer360 import build_customer_360
from .models import Customer


@login_required
@user_passes_test(is_admin_or_employee)
@require_GET
def customer_360(request, customer_id):
    customer = get_object_or_404(Customer.objects.select_related("user"), id=customer_id)
    # Every look at a customer's page leaves a line in the audit log.
    log_action(
        Actions.CUSTOMER_VIEWED, request=request,
        target_type="CUSTOMER", target_id=customer.id,
        details=f"{customer.user.username}: Customer 360 page opened",
    )
    context = build_customer_360(customer)
    # Only Customer Support and admins can open the staff case page.
    context["can_open_cases"] = can_manage_cases(request.user)
    return render(request, "users/customer_360.html", context)