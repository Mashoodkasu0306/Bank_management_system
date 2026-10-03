"""The questions the reports ask the database. No web code here."""
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate

from accounts.models import Account
from bank.models import Branch
from transactions.models import Transaction
from users.models import Customer

MAX_RANGE_DAYS = 366
TYPES = (("DEPOSIT", "deposit"), ("WITHDRAW", "withdraw"), ("TRANSFER", "transfer"))


def transactions_in_scope(start, end, branch=None):
    """Transactions between two dates (inclusive). With a branch: a deposit belongs to the
    receiving account's branch; a withdrawal or transfer belongs to the sending account's
    branch. So a transfer is counted once, and branches add up to the bank total."""
    qs = Transaction.objects.filter(timestamp__date__gte=start, timestamp__date__lte=end)
    if branch is not None:
        qs = qs.filter(
            Q(transaction_type="DEPOSIT", to_account__branch=branch)
            | Q(transaction_type__in=["WITHDRAW", "TRANSFER"], from_account__branch=branch)
        )
    return qs


def _empty_row(day):
    row = {"day": day}
    for _, prefix in TYPES:
        row[prefix + "_count"] = 0
        row[prefix + "_total"] = Decimal("0.00")
    return row


def totals_by_day(start, end, branch=None):
    """Successful, ordinary transactions per day and type. Loan payouts and loan
    repayments are left out here; they belong to the loans section."""
    rows = (
        transactions_in_scope(start, end, branch)
        .filter(status="SUCCESS", is_loan_related=False)
        .annotate(day=TruncDate("timestamp"))
        .values("day", "transaction_type")
        .annotate(count=Count("id"), total=Sum("amount"))
        .order_by()
    )
    prefixes = dict(TYPES)
    by_day = {}
    for r in rows:
        prefix = prefixes[r["transaction_type"]]
        entry = by_day.setdefault(r["day"], _empty_row(r["day"]))
        entry[prefix + "_count"] = r["count"]
        entry[prefix + "_total"] = r["total"] or Decimal("0.00")

    days = [by_day[d] for d in sorted(by_day)]
    grand = _empty_row(None)
    for entry in days:
        for key, value in entry.items():
            if key != "day":
                grand[key] += value
    return days, grand


def failed_transactions(start, end, branch=None):
    return (
        transactions_in_scope(start, end, branch)
        .filter(status="FAILED")
        .select_related("from_account", "to_account", "performed_by")
        .order_by("-timestamp")
    )


def new_accounts(start, end, branch=None):
    qs = Account.objects.filter(open_date__gte=start, open_date__lte=end)
    if branch is not None:
        qs = qs.filter(branch=branch)
    return qs.select_related("customer__user", "branch").order_by("-open_date", "-id")


def new_customers(start, end, branch=None):
    """Customers who joined in the range. A customer has no branch of their own, so with a
    branch chosen we count those who have an account in that branch."""
    qs = Customer.objects.filter(
        user__date_joined__date__gte=start, user__date_joined__date__lte=end
    )
    if branch is not None:
        qs = qs.filter(accounts__branch=branch).distinct()
    return qs.select_related("user").order_by("-user__date_joined", "-id")


def branch_summary(start, end):
    """One row per branch. Loan columns are added in the loans step."""
    rows = []
    for branch in Branch.objects.order_by("name"):
        _, grand = totals_by_day(start, end, branch)
        rows.append({
            "branch": branch,
            "txn_count": grand["deposit_count"] + grand["withdraw_count"] + grand["transfer_count"],
            "deposit_total": grand["deposit_total"],
            "withdraw_total": grand["withdraw_total"],
            "transfer_total": grand["transfer_total"],
            "new_accounts": new_accounts(start, end, branch).count(),
            "new_customers": new_customers(start, end, branch).count(),
        })
    return rows