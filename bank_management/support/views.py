from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from users.models import Customer, Employee

from . import services
from .forms import CaseForm, ReplyForm
from .models import SupportCase


def customer_only(view_func):
    """Only customers use these pages. Staff are sent back to their own dashboard."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        customer = Customer.objects.filter(user=request.user).first()
        if customer is None:
            messages.error(request, "Only customers can raise and follow their own cases.")
            if Employee.objects.filter(user=request.user).exists():
                return redirect("employee_dashboard")
            return redirect("admin_dashboard")
        request.customer = customer
        return view_func(request, *args, **kwargs)
    return wrapper


@login_required
@customer_only
def my_cases(request):
    cases = list(SupportCase.objects.filter(customer=request.customer))
    return render(request, "support/my_cases.html", {
        "open_cases": [c for c in cases if c.is_open],
        "decided_cases": [c for c in cases if not c.is_open],
    })


@login_required
@customer_only
def raise_case(request):
    if request.method == "POST":
        form = CaseForm(request.POST, customer=request.customer)
        if form.is_valid():
            cd = form.cleaned_data
            try:
                case = services.open_case(
                    request, request.customer,
                    case_type=cd["case_type"], category=cd["category"],
                    subject=cd["subject"], description=cd["description"],
                    account=cd.get("account"), transaction=cd.get("transaction"),
                )
            except services.CaseError as error:
                messages.error(request, str(error))
            else:
                messages.success(request, f"Your case {case.reference} was sent to the bank.")
                return redirect("support_case_detail", case_id=case.id)
    else:
        kind = request.GET.get("type")
        initial = {"case_type": kind} if kind in dict(SupportCase.TYPE_CHOICES) else {}
        form = CaseForm(customer=request.customer, initial=initial)
    return render(request, "support/raise_case.html", {
        "form": form, "deadlines": SupportCase.DEADLINE_DAYS,
    })


@login_required
@customer_only
def case_detail(request, case_id):
    case = get_object_or_404(
        SupportCase.objects.select_related("account", "transaction"),
        id=case_id, customer=request.customer,
    )
    return render(request, "support/case_detail.html", {
        "case": case, "thread": case.messages.all(), "form": ReplyForm(),
    })


@login_required
@customer_only
@require_POST
def reply_to_case(request, case_id):
    case = get_object_or_404(SupportCase, id=case_id, customer=request.customer)
    form = ReplyForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please write a reply (up to 2000 characters).")
    else:
        try:
            services.customer_reply(request, case, form.cleaned_data["body"])
        except services.CaseError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, "Your reply was sent.")
    return redirect("support_case_detail", case_id=case.id)