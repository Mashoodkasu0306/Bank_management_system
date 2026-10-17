from django.urls import reverse

from loans.models import Loan
from services.models import ATMCardRequest, ChequebookRequest, KYCDocument
from transactions.models import Transaction

# key -> (label, url name, small hint, function that counts)
CARDS = {
    "transactions": ("Pending approvals", "pending_transactions", "transactions waiting for a decision",
                     lambda: Transaction.objects.filter(status="PENDING").count()),
    "loans": ("Loan applications", "pending_loans", "waiting for review",
              lambda: Loan.objects.filter(status="PENDING").count()),
    "kyc": ("KYC documents", "pending_kyc_documents", "awaiting verification",
            lambda: KYCDocument.objects.filter(verification_status="PENDING").count()),
    "atm": ("ATM card requests", "pending_atm_card_requests", "waiting for review",
            lambda: ATMCardRequest.objects.filter(status="PENDING").count()),
    "cheque": ("Cheque book requests", "pending_cheque_book_requests", "waiting for review",
               lambda: ChequebookRequest.objects.filter(status="PENDING").count()),
}

DEFAULT_ORDER = ["transactions", "loans", "kyc", "atm", "cheque"]

# The cards each department sees first. Nothing is hidden, only reordered.
FIRST_FOR_DEPARTMENT = {
    "TRANSACTIONS": ["transactions"],
    "LOANS": ["loans"],
    "KYC": ["kyc"],
    "CARDS_SERVICES": ["atm", "cheque"],
}


def employee_kpis(department):
    """The pending-work cards for the employee dashboard, own department first."""
    first = FIRST_FOR_DEPARTMENT.get(department, [])
    order = first + [key for key in DEFAULT_ORDER if key not in first]
    result = []
    for key in order:
        label, url_name, hint, count = CARDS[key]
        result.append({
            "key": key,
            "label": label,
            "value": count(),
            "hint": hint,
            "url": reverse(url_name),
            "mine": key in first,
        })
    return result