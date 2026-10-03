"""Loan questions for the reports. No web code here."""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone

from loans.models import Loan, LoanRepayment

from . import services

ZERO = Decimal("0.00")
ACTIVE_STATUSES = ("APPROVED", "DEFAULTED")
OVERDUE_BUCKETS = (
    ("1-30 days", 1, 30),
    ("31-60 days", 31, 60),
    ("61-90 days", 61, 90),
    ("91-180 days", 91, 180),
    ("Over 180 days", 181, None),
)
EMI_REMARK = "EMI payment"
FORECLOSURE_REMARK = "Loan foreclosure"


def loans_in_scope(branch=None):
    """A loan has no branch of its own; it belongs to the branch of its account."""
    qs = Loan.objects.all()
    if branch is not None:
        qs = qs.filter(account__branch=branch)
    return qs


def loan_status_counts(branch=None):
    counts = dict(
        loans_in_scope(branch).order_by().values_list("status").annotate(c=Count("id"))
    )
    rows = [
        {"code": code, "label": label, "count": counts.get(code, 0)}
        for code, label in Loan.STATUS_CHOICES
    ]
    return rows, sum(counts.values())


def loan_outstanding(branch=None):
    """Money still owed on active loans, as of today."""
    active = loans_in_scope(branch).filter(status__in=ACTIVE_STATUSES)
    emi = active.filter(repayment_type="EMI")
    lump = active.filter(repayment_type="LUMP_SUM", lump_sum_total_payable__isnull=False)

    lent = emi.aggregate(t=Sum("amount"))["t"] or ZERO
    schedule = LoanRepayment.objects.filter(loan__in=emi)
    paid_principal = schedule.filter(status="PAID").aggregate(t=Sum("principal_component"))["t"] or ZERO
    interest_ahead = schedule.filter(status="PENDING").aggregate(t=Sum("interest_component"))["t"] or ZERO

    lump_totals = lump.aggregate(payable=Sum("lump_sum_total_payable"), paid=Sum("lump_sum_paid"))
    lump_remaining = (lump_totals["payable"] or ZERO) - (lump_totals["paid"] or ZERO)

    return {
        "emi_loans": emi.count(),
        "outstanding_principal": max(lent - paid_principal, ZERO),
        "scheduled_interest": interest_ahead,
        "lump_loans": lump.count(),
        "lump_remaining": max(lump_remaining, ZERO),
    }


def _count_and_total(qs):
    agg = qs.aggregate(n=Count("id"), t=Sum("amount"))
    return {"count": agg["n"], "total": agg["t"] or ZERO}


def loan_money(start, end, branch=None):
    """Loan payouts and loan repayments in the period (successful ones only).
    A payout is a loan-related DEPOSIT; every repayment is a loan-related WITHDRAW."""
    qs = services.transactions_in_scope(start, end, branch).filter(
        is_loan_related=True, status="SUCCESS"
    )
    repay = qs.filter(transaction_type="WITHDRAW")
    return {
        "payouts": _count_and_total(qs.filter(transaction_type="DEPOSIT")),
        "emi": _count_and_total(repay.filter(remarks__startswith=EMI_REMARK)),
        "foreclosure": _count_and_total(repay.filter(remarks__startswith=FORECLOSURE_REMARK)),
        "other": _count_and_total(
            repay.exclude(remarks__startswith=EMI_REMARK).exclude(remarks__startswith=FORECLOSURE_REMARK)
        ),
        "repayments": _count_and_total(repay),
    }


def _overdue_base(branch, today):
    qs = LoanRepayment.objects.filter(
        status="PENDING", due_date__lt=today, loan__status__in=ACTIVE_STATUSES
    )
    if branch is not None:
        qs = qs.filter(loan__account__branch=branch)
    return qs


def _bucket_label(days_late):
    for label, low, high in OVERDUE_BUCKETS:
        if days_late >= low and (high is None or days_late <= high):
            return label
    return ""


def overdue_by_bucket(branch=None, today=None):
    """Unpaid installments past their due date, by how many days late (as of today)."""
    today = today or timezone.localdate()
    base = _overdue_base(branch, today)
    rows = []
    for label, low, high in OVERDUE_BUCKETS:
        qs = base.filter(due_date__lte=today - timedelta(days=low))
        if high is not None:
            qs = qs.filter(due_date__gte=today - timedelta(days=high))
        agg = qs.aggregate(n=Count("id"), loans=Count("loan", distinct=True), amount=Sum("emi_amount"))
        rows.append({
            "label": label, "installments": agg["n"],
            "loans": agg["loans"], "amount": agg["amount"] or ZERO,
        })
    agg = base.aggregate(n=Count("id"), loans=Count("loan", distinct=True), amount=Sum("emi_amount"))
    total = {
        "label": "Total", "installments": agg["n"],
        "loans": agg["loans"], "amount": agg["amount"] or ZERO,
    }
    return rows, total


# ---- rows for the CSV files ----

def loan_summary_rows(start, end, branch=None):
    status_rows, total = loan_status_counts(branch)
    out = [[f"Loans - {r['label']}", r["count"], ""] for r in status_rows]
    out.append(["Loans - Total", total, ""])

    o = loan_outstanding(branch)
    out.append(["Outstanding principal (EMI loans)", o["emi_loans"], o["outstanding_principal"]])
    out.append(["Interest still to come (EMI schedule)", o["emi_loans"], o["scheduled_interest"]])
    out.append(["Remaining on lump-sum loans", o["lump_loans"], o["lump_remaining"]])

    m = loan_money(start, end, branch)
    out.append(["Loans paid out in period", m["payouts"]["count"], m["payouts"]["total"]])
    out.append(["Repayments - EMI", m["emi"]["count"], m["emi"]["total"]])
    out.append(["Repayments - foreclosure", m["foreclosure"]["count"], m["foreclosure"]["total"]])
    out.append(["Repayments - lump sum and other", m["other"]["count"], m["other"]["total"]])
    out.append(["Repayments - total", m["repayments"]["count"], m["repayments"]["total"]])
    return out


def overdue_summary_rows(branch=None):
    rows, total = overdue_by_bucket(branch)
    return [[r["label"], r["installments"], r["loans"], r["amount"]] for r in rows + [total]]


def overdue_detail_rows(branch=None):
    today = timezone.localdate()
    qs = (
        _overdue_base(branch, today)
        .select_related("loan__customer__user", "loan__account")
        .order_by("due_date", "loan_id", "installment_number")
    )
    out = []
    for r in qs:
        days_late = (today - r.due_date).days
        out.append([
            r.loan_id, r.loan.customer.user.get_username(), r.loan.account.account_no,
            r.installment_number, r.due_date, days_late, r.emi_amount, _bucket_label(days_late),
        ])
    return out


def branch_summary_with_loans(start, end):
    """The branch summary from services, plus the loan columns."""
    rows = services.branch_summary(start, end)
    for row in rows:
        branch = row["branch"]
        row["active_loans"] = loans_in_scope(branch).filter(status="APPROVED").count()
        row["overdue_amount"] = overdue_by_bucket(branch)[1]["amount"]
    return rows