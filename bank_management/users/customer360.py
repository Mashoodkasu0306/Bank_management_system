"""Everything the Customer 360 page shows, gathered in one place. Read-only:
nothing here changes the database."""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from .security_feed import failed_logins_since, feed_for

RECENT_TRANSACTIONS = 10
RECENT_LOANS = 10
RECENT_CARDS = 5
RECENT_CHEQUE_BOOKS = 5
RECENT_CASES = 5
RECENT_SECURITY = 10

# Only these account types count towards the total balance shown to staff.
BALANCE_TYPES = ("SAVINGS", "CURRENT")


def _loan_row(loan, today):
    """One loan plus what staff want to know about it right now."""
    row = {"loan": loan, "remaining": None, "next_installment": None, "overdue_count": 0}
    if loan.status != "APPROVED":
        return row
    row["remaining"] = loan.get_remaining_amount()
    if loan.repayment_type == "EMI":
        pending = loan.repayments.filter(status="PENDING").order_by("installment_number")
        row["next_installment"] = pending.first()
        row["overdue_count"] = pending.filter(due_date__lt=today).count()
    return row


def build_customer_360(customer):
    # Imported here, as the Security Activity page does, so this file never
    # causes a circular import when the apps load.
    from loans.models import Loan
    from services.freeze import get_active_freeze
    from services.models import ATMCardRequest, ChequebookRequest, KYCVerification
    from support.models import SupportCase
    from transactions.models import Transaction

    now = timezone.now()
    today = timezone.localdate()

    accounts = list(customer.accounts.select_related("branch").order_by("account_no"))
    total_balance = sum(
        (a.balance for a in accounts if a.status == "ACTIVE" and a.account_type in BALANCE_TYPES),
        Decimal("0.00"),
    )

    transactions = list(
        Transaction.objects.filter(
            Q(from_account__customer=customer) | Q(to_account__customer=customer)
        )
        .select_related("from_account", "to_account")
        .distinct()
        .order_by("-timestamp", "-id")[:RECENT_TRANSACTIONS]
    )

    loans = list(
        Loan.objects.filter(customer=customer)
        .select_related("account")
        .order_by("-applied_date", "-id")[:RECENT_LOANS]
    )

    cards = list(
        ATMCardRequest.objects.filter(account__customer=customer)
        .select_related("account")
        .order_by("-requested_at", "-id")[:RECENT_CARDS]
    )
    cheque_books = list(
        ChequebookRequest.objects.filter(account__customer=customer)
        .select_related("account")
        .order_by("-requested_at", "-id")[:RECENT_CHEQUE_BOOKS]
    )

    cases = list(
        SupportCase.objects.filter(customer=customer).order_by("-created_at", "-id")[:RECENT_CASES]
    )
    open_case_count = SupportCase.objects.filter(
        customer=customer, status__in=SupportCase.OPEN_STATUSES
    ).count()

    return {
        "customer": customer,
        "kyc": KYCVerification.objects.filter(customer=customer).first(),
        "freeze": get_active_freeze(customer),
        "accounts": accounts,
        "total_balance": total_balance,
        "recent_transactions": transactions,
        "loans": [_loan_row(loan, today) for loan in loans],
        "cards": cards,
        "cheque_books": cheque_books,
        "cases": cases,
        "open_case_count": open_case_count,
        "security_rows": feed_for(customer, limit=RECENT_SECURITY),
        "failed_week": failed_logins_since(customer.user, now - timedelta(days=7)),
    }