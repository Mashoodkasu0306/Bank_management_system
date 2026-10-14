"""The customer's Savings Goals pages. Tracking only: nothing here moves money."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .forms import SavingsGoalForm
from .goals import goals_for
from .models import SavingsGoal


def _customer(request):
    customer = getattr(request.user, "customer", None)
    if customer is None:
        messages.error(request, "Only customers have savings goals.")
    return customer


@login_required
@require_GET
def my_goals(request):
    customer = _customer(request)
    if customer is None:
        return redirect("home")
    return render(request, "planning/goals.html", {"goals": goals_for(customer)})


@login_required
@require_http_methods(["GET", "POST"])
def goal_create(request):
    customer = _customer(request)
    if customer is None:
        return redirect("home")

    form = SavingsGoalForm(request.POST if request.method == "POST" else None, customer=customer)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Goal created.")
        return redirect("my_goals")
    return render(request, "planning/goal_form.html", {"form": form, "title": "New savings goal"})


@login_required
@require_http_methods(["GET", "POST"])
def goal_edit(request, goal_id):
    customer = _customer(request)
    if customer is None:
        return redirect("home")

    goal = get_object_or_404(
        SavingsGoal, id=goal_id, customer=customer, status=SavingsGoal.ACTIVE
    )
    form = SavingsGoalForm(
        request.POST if request.method == "POST" else None, instance=goal, customer=customer
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Goal updated.")
        return redirect("my_goals")
    return render(request, "planning/goal_form.html", {"form": form, "title": "Edit savings goal"})


@login_required
@require_POST
def goal_archive(request, goal_id):
    customer = _customer(request)
    if customer is None:
        return redirect("home")

    goal = get_object_or_404(
        SavingsGoal, id=goal_id, customer=customer, status=SavingsGoal.ACTIVE
    )
    goal.status = SavingsGoal.ARCHIVED
    goal.save(update_fields=["status", "updated_at"])
    messages.success(request, "Goal archived.")
    return redirect("my_goals")