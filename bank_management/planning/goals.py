"""Savings goal numbers. Tracking only: nothing here moves, reserves or blocks money."""
from decimal import Decimal, ROUND_DOWN

from django.utils import timezone

from .models import SavingsGoal

ZERO = Decimal("0.00")


def goal_progress(goal, today=None):
    today = today or timezone.localdate()
    account = goal.account
    balance = max(Decimal(str(account.balance)), ZERO)
    target = goal.target_amount

    saved = min(balance, target)
    if target > 0:
        # Rounded down, so 99.99% never shows as 100% before the target is really reached.
        percent = int((saved * 100 / target).quantize(Decimal("1"), rounding=ROUND_DOWN))
    else:
        percent = 0
    achieved = target > 0 and balance >= target

    days_left = None
    overdue = False
    if goal.target_date is not None:
        days_left = max((goal.target_date - today).days, 0)
        overdue = (not achieved) and goal.target_date < today

    return {
        "balance": balance,
        "target": target,
        "saved": saved,
        "remaining": target - saved,
        "percent": percent,
        "achieved": achieved,
        "days_left": days_left,
        "overdue": overdue,
        "account_active": account.status == "ACTIVE",
    }


def goals_for(customer, today=None):
    """The customer's active goals, oldest first, each with its live progress."""
    goals = (
        SavingsGoal.objects.filter(customer=customer, status=SavingsGoal.ACTIVE)
        .select_related("account")
        .order_by("created_at", "id")
    )
    return [{"goal": goal, **goal_progress(goal, today)} for goal in goals]