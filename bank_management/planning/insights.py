"""Money Insights numbers for the customer's page. Read only: nothing here changes data."""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from accounts.models import Account
from loans.models import Loan, LoanRepayment
from users.spending import month_summary, shift_month

from .goals import goals_for
from .models import RecurringPayment
from .recurring import next_run_after

ZERO = Decimal("0.00")
WINDOW_DAYS = 30
MONTHS_SHOWN = 6
MAX_OCCURRENCES = 40
ACTIVE_LOAN_STATUSES = ("APPROVED", "DEFAULTED")
DEBT_LABELS = {"NONE": "No active loans", "OK": "On track", "ATTENTION": "Needs attention"}


def _recurring_items(customer, today, window_end, my_account_ids):
    """Every date a recurring payment falls due inside the window."""
    items = []
    payments = (
        RecurringPayment.objects.filter(customer=customer, status=RecurringPayment.ACTIVE)
        .select_related("from_account", "to_account")
    )
    for payment in payments:
        own = payment.to_account_id in my_account_ids  # your own money moving between your accounts
        current = payment.next_run_date
        for _ in range(MAX_OCCURRENCES):
            if current > window_end:
                break
            if payment.end_date and current > payment.end_date:
                break
            items.append({
                "date": current,
                "kind": "RECURRING",
                "label": payment.name,
                "detail": f"to {payment.to_account.account_no}",
                "amount": payment.amount,
                "overdue": current < today,
                "counted": not own,
            })
            if current < today:
                # Not run yet: the runner pays it once, then carries on from the first date after today.
                while current <= today:
                    current = next_run_after(payment, current)
            else:
                current = next_run_after(payment, current)
    return items


def _emi_items(customer, today, window_end):
    repayments = (
        LoanRepayment.objects.filter(
            loan__customer=customer, loan__status__in=ACTIVE_LOAN_STATUSES,
            status="PENDING", due_date__lte=window_end,
        )
        .select_related("loan")
        .order_by("due_date", "installment_number")
    )
    return [
        {
            "date": repayment.due_date,
            "kind": "EMI",
            "label": f"{repayment.loan.get_loan_type_display()} loan #{repayment.loan_id} EMI {repayment.installment_number}",
            "detail": "",
            "amount": repayment.emi_amount,
            "overdue": repayment.due_date < today,
            "counted": True,
        }
        for repayment in repayments
    ]


def _cash_flow(customer, today):
    """The last few months, oldest first, ending with the month of `today`."""
    rows = []
    for back in range(MONTHS_SHOWN - 1, -1, -1):
        year, month = shift_month(today.year, today.month, -back)
        summary = month_summary(customer, year, month)
        rows.append({
            "key": f"{year:04d}-{month:02d}",
            "label": summary["month_label"],
            "income": summary["income"],
            "out": summary["total_out"],
            "net": summary["net"],
            "loan_received": summary["loan_received"],
        })
    peak = max([max(row["income"], row["out"]) for row in rows] + [ZERO])
    for row in rows:
        row["income_pct"] = int(row["income"] * 100 / peak) if peak > 0 else 0
        row["out_pct"] = int(row["out"] * 100 / peak) if peak > 0 else 0
    return rows


def _debt(customer, today, months):
    rows = []
    for loan in Loan.objects.filter(customer=customer, status__in=ACTIVE_LOAN_STATUSES).order_by("id"):
        if loan.repayment_type == "LUMP_SUM":
            # No instalments: what is left is the total payable minus what has been paid.
            pending = []
            outstanding = loan.get_lump_sum_remaining()
        else:
            pending = list(loan.repayments.filter(status="PENDING").order_by("due_date"))
            outstanding = loan.get_outstanding_principal()
        if outstanding <= 0 and not pending:
            continue
        overdue = [repayment for repayment in pending if repayment.due_date < today]
        rows.append({
            "id": loan.id,
            "type": loan.get_loan_type_display(),
            "status": loan.status,
            "outstanding": outstanding,
            "emi_amount": loan.emi_amount or ZERO,
            "next_due": pending[0].due_date if pending else None,
            "overdue_count": len(overdue),
            "overdue_amount": sum((repayment.emi_amount for repayment in overdue), ZERO),
            "days_overdue": max(((today - repayment.due_date).days for repayment in overdue), default=0),
        })

    total_outstanding = sum((row["outstanding"] for row in rows), ZERO)
    monthly_emi_total = sum((row["emi_amount"] for row in rows if row["next_due"] is not None), ZERO)
    overdue_total = sum((row["overdue_amount"] for row in rows), ZERO)

    previous = months[-4:-1]  # the three months before the current one
    average_income = sum((m["income"] for m in previous), ZERO) / len(previous) if previous else ZERO
    emi_share = None
    if monthly_emi_total > 0 and average_income > 0:
        emi_share = int(monthly_emi_total * 100 / average_income)

    if not rows:
        status = "NONE"
    elif overdue_total > 0 or any(row["status"] == "DEFAULTED" for row in rows):
        status = "ATTENTION"
    else:
        status = "OK"

    return {
        "status": status,
        "label": DEBT_LABELS[status],
        "rows": rows,
        "total_outstanding": total_outstanding,
        "monthly_emi_total": monthly_emi_total,
        "overdue_total": overdue_total,
        "emi_share_percent": emi_share,
    }


def build_insights(customer, today=None):
    today = today or timezone.localdate()
    window_end = today + timedelta(days=WINDOW_DAYS)

    accounts = list(
        Account.objects.filter(
            customer=customer, status="ACTIVE", account_type__in=["SAVINGS", "CURRENT"]
        ).order_by("account_no")
    )
    my_account_ids = set(Account.objects.filter(customer=customer).values_list("id", flat=True))
    balance_total = sum((account.balance for account in accounts), ZERO)

    upcoming = _recurring_items(customer, today, window_end, my_account_ids)
    upcoming += _emi_items(customer, today, window_end)
    upcoming.sort(key=lambda item: (item["date"], item["kind"], item["label"]))
    upcoming_total = sum((item["amount"] for item in upcoming if item["counted"]), ZERO)
    safe_to_spend = balance_total - upcoming_total

    months = _cash_flow(customer, today)

    return {
        "today": today,
        "window_end": window_end,
        "window_days": WINDOW_DAYS,
        "accounts": [
            {
                "account_no": account.account_no,
                "type": account.get_account_type_display(),
                "balance": account.balance,
            }
            for account in accounts
        ],
        "balance_total": balance_total,
        "upcoming": upcoming,
        "upcoming_total": upcoming_total,
        "safe_to_spend": safe_to_spend,
        "shortfall": safe_to_spend < 0,
        "months": months,
        "goals": goals_for(customer, today),
        "debt": _debt(customer, today, months),
    }