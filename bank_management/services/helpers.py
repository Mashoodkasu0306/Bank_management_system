from decimal import Decimal
from datetime import timedelta
from functools import wraps
from django.utils import timezone
from django.db.models import Q
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.contrib import messages
from django.shortcuts import redirect
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors

from transactions.models import Transaction


# ============================================================================
# KYC HELPERS
# ============================================================================

def get_kyc_requirements(customer):
    """
    Option A: income proof is only mandatory when applying for a loan,
    not at account-opening/KYC time.
    """
    mandatory = ["ID_PROOF", "PAN", "ADDRESS_PROOF"]
    optional = ["INCOME_PROOF"]
    return mandatory, optional


def check_income_proof_for_loan(kyc_verification):
    """Call this from loans/views.py apply_loan() before eligibility checks."""
    income_doc = kyc_verification.documents.filter(
        document_type="INCOME_PROOF",
        verification_status="VERIFIED"
    ).first()

    if not income_doc:
        return False, "Income proof document not yet verified. Please upload and get it verified."
    return True, ""


# ============================================================================
# ATM CARD ELIGIBILITY
# ============================================================================

def check_atm_card_eligibility(account):
    if account.status != "ACTIVE":
        return False, f"Account status is {account.status}. Only active accounts can request ATM cards."

    if account.account_type not in ["SAVINGS", "CURRENT"]:
        return False, f"Account type {account.account_type} is not eligible for ATM cards."

    kyc = account.customer.kyc_verification
    if not kyc.is_fully_verified():
        return False, "Your KYC verification is not complete. Please complete KYC first."

    active_card = account.atm_card_requests.filter(status__in=["PENDING", "APPROVED"]).first()
    if active_card:
        return False, f"You already have an active ATM card request (status: {active_card.status})."

    return True, ""


# ============================================================================
# CHEQUE BOOK ELIGIBILITY
# ============================================================================

def check_cheque_book_eligibility(account):
    """
    Check if account is eligible for cheque book.
    Rules:
    - Only SAVINGS/CURRENT accounts
    - Minimum balance Rs.1,000
    - No duplicate pending requests

    (Account-age minimums apply to LOANS only, via
    LoanEligibilityRule.min_account_age_days — not to cheque books or ATM
    cards, which have no age requirement.)

    Returns (is_eligible, reason).
    """
    # Only SAVINGS/CURRENT
    if account.account_type not in ["SAVINGS", "CURRENT"]:
        return False, f"Account type {account.account_type} is not eligible for cheque books."

    # Balance check
    if account.balance < Decimal("1000.00"):
        return False, f"Minimum balance of Rs.1,000 required. Current balance: Rs.{account.balance}."

    # No duplicate pending/approved requests
    duplicate = account.cheque_requests.filter(status__in=["PENDING", "APPROVED"]).first()
    if duplicate:
        return False, f"You already have an active cheque book request (status: {duplicate.status})."

    return True, ""


# ============================================================================
# STATEMENT GENERATION
# ============================================================================

def get_statement_transactions(account, start_date, end_date):
    return Transaction.objects.filter(
        Q(from_account=account, status="SUCCESS") | Q(to_account=account, status="SUCCESS"),
        timestamp__date__gte=start_date,
        timestamp__date__lte=end_date
    ).order_by("timestamp")


def calculate_statement_balances(account, transactions, start_date):
    """
    Reconstructs opening/closing balance for the period by replaying
    transaction history (your Account model has no balance-history table,
    only a running `balance` field).
    """
    transactions_before = Transaction.objects.filter(
        Q(from_account=account, status="SUCCESS") | Q(to_account=account, status="SUCCESS"),
        timestamp__date__lt=start_date
    ).order_by("timestamp")

    opening_balance = Decimal("0.00")
    for txn in transactions_before:
        if txn.from_account_id == account.id:
            opening_balance -= txn.amount
        else:
            opening_balance += txn.amount

    closing_balance = opening_balance
    for txn in transactions:
        if txn.from_account_id == account.id:
            closing_balance -= txn.amount
        else:
            closing_balance += txn.amount

    return opening_balance, closing_balance


def generate_statement_pdf(account, start_date, end_date, requested_by_user=None):
    transactions = get_statement_transactions(account, start_date, end_date)
    opening_balance, closing_balance = calculate_statement_balances(account, transactions, start_date)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=0.5*inch, leftMargin=0.5*inch)
    story = []

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontSize=16,
                                  textColor=colors.HexColor('#1a1a1a'), spaceAfter=12, alignment=1)
    heading_style = ParagraphStyle('CustomHeading', parent=styles['Heading2'], fontSize=11,
                                    textColor=colors.HexColor('#333333'), spaceAfter=8)

    story.append(Paragraph("ACCOUNT STATEMENT", title_style))
    story.append(Spacer(1, 0.3*inch))

    details_data = [
        ["Account Holder:", account.customer.user.get_full_name() or account.customer.user.username],
        ["Account Number:", f"****{account.account_no[-4:]}"],
        ["Account Type:", account.get_account_type_display()],
        ["Branch:", account.branch.name],
        ["Statement Period:", f"{start_date} to {end_date}"],
        ["Generated On:", timezone.now().strftime("%Y-%m-%d %H:%M:%S")],
    ]
    details_table = Table(details_data, colWidths=[2*inch, 4*inch])
    details_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f0f0')),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    story.append(details_table)
    story.append(Spacer(1, 0.2*inch))

    story.append(Paragraph("Summary", heading_style))
    total_deposits = sum((t.amount for t in transactions if t.to_account_id == account.id), Decimal("0.00"))
    total_withdrawals = sum((t.amount for t in transactions if t.from_account_id == account.id), Decimal("0.00"))
    summary_data = [
        ["Opening Balance:", f"Rs. {opening_balance:,.2f}"],
        ["Total Deposits:", f"Rs. {total_deposits:,.2f}"],
        ["Total Withdrawals:", f"Rs. {total_withdrawals:,.2f}"],
        ["Closing Balance:", f"Rs. {closing_balance:,.2f}"],
    ]
    summary_table = Table(summary_data, colWidths=[2*inch, 4*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#e8f4f8')),
        ('BACKGROUND', (0, 3), (-1, 3), colors.HexColor('#d0e8f2')),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (0, 3), (-1, 3), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 0.3*inch))

    story.append(Paragraph("Transactions", heading_style))
    if transactions:
        trans_data = [["Date", "Description", "Amount", "Type", "Balance"]]
        running_balance = opening_balance
        for txn in transactions:
            if txn.from_account_id == account.id:
                amount_str = f"-Rs. {txn.amount:,.2f}"
                running_balance -= txn.amount
                trans_type = "Debit"
            else:
                amount_str = f"+Rs. {txn.amount:,.2f}"
                running_balance += txn.amount
                trans_type = "Credit"
            description = txn.remarks[:40] if txn.remarks else txn.get_transaction_type_display()
            trans_data.append([
                txn.timestamp.strftime("%Y-%m-%d"), description, amount_str, trans_type,
                f"Rs. {running_balance:,.2f}"
            ])

        trans_table = Table(trans_data, colWidths=[1.2*inch, 2.3*inch, 1.2*inch, 0.7*inch, 1.1*inch])
        trans_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4472C4')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (2, 0), (4, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(trans_table)
    else:
        story.append(Paragraph("No transactions in this period.", styles['Normal']))

    doc.build(story)
    buffer.seek(0)
    return buffer


# ============================================================================
# VALIDATORS
# ============================================================================

def validate_date_range(start_date, end_date):
    if start_date > end_date:
        raise ValidationError("Start date must be before or equal to end date.")
    if (end_date - start_date).days > 365:
        raise ValidationError("Date range cannot exceed 1 year (365 days).")


def get_preset_date_range(period_name):
    today = timezone.localdate()
    if period_name == "last_30":
        return today - timedelta(days=30), today
    elif period_name == "last_90":
        return today - timedelta(days=90), today
    elif period_name == "last_180":
        return today - timedelta(days=180), today
    elif period_name == "last_365":
        return today - timedelta(days=365), today
    return None, None


# ============================================================================
# CARD NUMBER / CVV / EXPIRY GENERATION
# ============================================================================
# Deterministic secure-random generation with a Luhn checksum. Full number
# + CVV are intentionally never persisted to the database — only the masked
# number and expiry date are stored, matching real PCI-DSS practice.

import secrets


def _luhn_check_digit(partial_number):
    digits = [int(d) for d in partial_number]
    digits.reverse()
    total = 0
    for i, d in enumerate(digits):
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - (total % 10)) % 10


def generate_card_number():
    """16-digit card number with a valid Luhn checksum, fake BIN prefix."""
    bin_prefix = "402400"
    body_length = 16 - len(bin_prefix) - 1
    body = ''.join(str(secrets.randbelow(10)) for _ in range(body_length))
    partial = bin_prefix + body
    check_digit = _luhn_check_digit(partial)
    return partial + str(check_digit)


def generate_cvv():
    return f"{secrets.randbelow(1000):03d}"


def generate_expiry_date():
    from datetime import date
    today = date.today()
    return date(today.year + 5, today.month, 1)


def mask_card_number(full_number):
    return f"XXXX-XXXX-XXXX-{full_number[-4:]}"


# ============================================================================
# KYC ENFORCEMENT DECORATOR
# ============================================================================

def require_verified_kyc(view_func):
    """
    Blocks a customer-only view unless their KYC is fully verified
    (ID_PROOF + PAN + ADDRESS_PROOF all VERIFIED).

    Apply AFTER @login_required so authentication is checked first:
        @login_required
        @require_verified_kyc
        def some_view(request):
            ...

    Redirects to kyc_dashboard with an explanatory message instead of
    letting the view run at all.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not hasattr(request.user, 'customer'):
            messages.error(request, "Only customers can access this feature.")
            return redirect('customer_dashboard')

        try:
            kyc = request.user.customer.kyc_verification
        except ObjectDoesNotExist:
            messages.error(request, "Please complete your KYC verification before using this feature.")
            return redirect('kyc_dashboard')

        if not kyc.is_fully_verified():
            messages.error(request, "Your KYC verification is not complete. Please complete KYC before using this feature.")
            return redirect('kyc_dashboard')

        return view_func(request, *args, **kwargs)
    return wrapper