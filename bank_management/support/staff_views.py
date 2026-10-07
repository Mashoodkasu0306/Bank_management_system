"""Staff side of support cases: the queue, the case page, and the actions."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from bank.views import is_admin
from users.models import Employee

from . import staff_services
from .forms import ReplyForm
from .models import SupportCase
from .services import CaseError
from .staff_forms import DecisionForm


def can_manage_cases(user):
    """Admins and Customer Support employees may work on support cases."""
    if not user.is_authenticated:
        return False
    return is_admin(user) or Employee.objects.filter(user=user, department="SUPPORT").exists()


@login_required
@user_passes_test(can_manage_cases)
def staff_cases(request):
    only_mine = request.GET.get("mine") == "1"
    open_qs = (
        SupportCase.objects.filter(status__in=SupportCase.OPEN_STATUSES)
        .select_related("customer__user", "assigned_to")
        .order_by("due_at", "id")
    )
    if only_mine:
        open_qs = open_qs.filter(assigned_to=request.user)
    open_cases = list(open_qs)
    decided_cases = (
        SupportCase.objects.filter(status__in=(SupportCase.ACCEPTED, SupportCase.REJECTED))
        .select_related("customer__user", "decided_by")
        .order_by("-decided_at", "-id")[:20]
    )
    return render(request, "support/staff/cases.html", {
        "open_cases": open_cases,
        "decided_cases": decided_cases,
        "only_mine": only_mine,
        "overdue_count": sum(1 for c in open_cases if c.is_overdue),
    })


@login_required
@user_passes_test(can_manage_cases)
def staff_case_detail(request, case_id):
    case = get_object_or_404(
        SupportCase.objects.select_related(
            "customer__user", "account", "transaction", "assigned_to", "decided_by"
        ),
        id=case_id,
    )
    return render(request, "support/staff/case_detail.html", {
        "case": case,
        "thread": case.messages.select_related("author"),
        "reply_form": ReplyForm(),
        "decision_form": DecisionForm(),
    })


def _run(request, case_id, action, success, *args):
    try:
        action(request, case_id, *args)
    except CaseError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, success)
    return redirect("support_staff_case", case_id=case_id)


@login_required
@user_passes_test(can_manage_cases)
@require_POST
def staff_pick_up(request, case_id):
    get_object_or_404(SupportCase, id=case_id)
    return _run(request, case_id, staff_services.pick_up_case, "You picked up this case.")


@login_required
@user_passes_test(can_manage_cases)
@require_POST
def staff_reply(request, case_id):
    get_object_or_404(SupportCase, id=case_id)
    form = ReplyForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please write a reply (up to 2000 characters).")
        return redirect("support_staff_case", case_id=case_id)
    return _run(
        request, case_id, staff_services.reply_as_staff,
        "Your reply was sent to the customer.", form.cleaned_data["body"],
    )


@login_required
@user_passes_test(can_manage_cases)
@require_POST
def staff_decide(request, case_id):
    get_object_or_404(SupportCase, id=case_id)
    form = DecisionForm(request.POST)
    if not form.is_valid():
        messages.error(
            request,
            "Please choose accept or reject and write an answer of at least 10 characters.",
        )
        return redirect("support_staff_case", case_id=case_id)
    return _run(
        request, case_id, staff_services.decide_case,
        "The decision was saved and the customer was told.",
        form.cleaned_data["decision"], form.cleaned_data["note"],
    )