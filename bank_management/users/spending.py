"""Numbers for the customer's Spending Summary page. Read only: nothing here changes data."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q
from django.utils import timezone

from accounts.models import Account
from transactions.models import Transaction

LOAN_PAYMENT = "LOAN_PAYMENT"
LABELS = dict(Transaction.CATEGORY_CHOICES)
LABELS[LOAN_PAYMENT] = "Loan payment"
ZERO = Decimal("0.00")


def current_month():
    today = timezone.localdate()
    return today.year, today.month


def shift_month(year, month, delta):
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def month_key(year, month):
    return f"{year:04d}-{month:02d}"


def parse_month(text):
    """Turns '2026-09' into (2026, 9). Anything odd, or a future month, gives this month."""
    now = current_month()
    try:
        year_text, month_text = (text or "").split("-")
        year, month = int(year_text), int(month_text)
        date(year, month, 1)
    except (ValueError, TypeError):
        return now
    if year < 2000 or (year, month) > now:
        return now
    return year, month


def month_summary(customer, year, month):
    start = date(year, month, 1)
    next_year, next_month = shift_month(year, month, 1)
    end = date(next_year, next_month, 1)  # the first day of the next month, not included

    my_ids = set(Account.objects.filter(customer=customer).values_list("id", flat=True))
    txns = (
        Transaction.objects.filter(
            status="SUCCESS", timestamp__date__gte=start, timestamp__date__lt=end,
        )
        .filter(Q(from_account_id__in=my_ids) | Q(to_account_id__in=my_ids))
    )

    spent = {}
    income = ZERO
    loan_received = ZERO
    own_transfers = 0

    for txn in txns:
        money_out = txn.from_account_id in my_ids
        money_in = txn.to_account_id in my_ids
        if money_out and money_in:
            own_transfers += 1
        elif money_out:
            code = LOAN_PAYMENT if txn.is_loan_related else txn.category
            spent[code] = spent.get(code, ZERO) + txn.amount
        elif money_in:
            if txn.is_loan_related:
                loan_received += txn.amount
            else:
                income += txn.amount

    total_out = sum(spent.values(), ZERO)
    rows = []
    for code, amount in sorted(spent.items(), key=lambda item: item[1], reverse=True):
        percent = int((amount * 100 / total_out).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        rows.append({
            "code": code,
            "label": LABELS.get(code, code),
            "amount": amount,
            "percent": percent,
        })

    now = current_month()
    prev_year, prev_month = shift_month(year, month, -1)
    has_next = (year, month) < now
    next_key = month_key(next_year, next_month) if has_next else None

    return {
        "year": year,
        "month": month,
        "month_label": start.strftime("%B %Y"),
        "prev_key": month_key(prev_year, prev_month),
        "next_key": next_key,
        "rows": rows,
        "total_out": total_out,
        "income": income,
        "loan_received": loan_received,
        "net": income - total_out,
        "own_transfers": own_transfers,
    }