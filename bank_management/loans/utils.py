from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta


def calculate_emi(principal, annual_rate, tenure_months):
    principal = Decimal(principal)
    annual_rate = Decimal(annual_rate)

    if annual_rate == 0:
        return (principal / tenure_months).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    monthly_rate = float(annual_rate / Decimal(100) / Decimal(12))
    p = float(principal)
    n = tenure_months

    emi = p * monthly_rate * (1 + monthly_rate) ** n / ((1 + monthly_rate) ** n - 1)
    return Decimal(str(round(emi, 2)))


def generate_amortization_schedule(principal, annual_rate, tenure_months, start_date):
    """Reducing-balance amortization: interest is charged only on the
    remaining balance each period, so the principal/interest split shifts
    over the life of the loan."""
    principal = Decimal(principal)
    annual_rate = Decimal(annual_rate)
    emi = calculate_emi(principal, annual_rate, tenure_months)
    monthly_rate = annual_rate / Decimal(100) / Decimal(12)

    schedule = []
    balance = principal
    due_date = start_date

    for i in range(1, tenure_months + 1):
        interest_component = (balance * monthly_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        principal_component = emi - interest_component

        if i == tenure_months:
            # Last installment: pay off whatever balance remains exactly,
            # absorbing any rounding drift from earlier periods.
            principal_component = balance
            installment_emi = principal_component + interest_component
        else:
            installment_emi = emi

        balance = balance - principal_component
        if balance < 0:
            balance = Decimal("0.00")

        due_date = due_date + timedelta(days=30)

        schedule.append({
            "installment_number": i,
            "due_date": due_date,
            "emi_amount": installment_emi.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "principal_component": principal_component.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "interest_component": interest_component,
            "closing_balance": balance.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        })

    return schedule


def get_income_proxy(account):
    """Rough income estimate: average monthly deposits over the last 3 months.
    This is NOT a real income verification - just a portfolio-appropriate stand-in."""
    from django.utils import timezone
    from django.db.models import Sum
    from transactions.models import Transaction

    three_months_ago = timezone.now() - timedelta(days=90)
    total = Transaction.objects.filter(
        to_account=account, transaction_type="DEPOSIT", status="SUCCESS", timestamp__gte=three_months_ago
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    return total / Decimal("3")


def check_eligibility(customer, account, loan_type, amount, tenure_months):
    """Soft eligibility check at application time. Returns (is_eligible, reasons)."""
    from django.utils import timezone
    from django.db.models import Sum
    from .models import LoanEligibilityRule, Loan

    reasons = []
    rule = LoanEligibilityRule.objects.filter(loan_type=loan_type).first()

    if rule is None:
        # No rule configured for this loan type yet - allow through, but this
        # should be set up by an admin via Django admin.
        return True, reasons

    if account.balance < rule.min_account_balance:
        reasons.append(f"Account balance ({account.balance}) is below the minimum required ({rule.min_account_balance}).")

    account_age_days = (timezone.localdate() - account.open_date).days
    if account_age_days < rule.min_account_age_days:
        reasons.append(f"Account must be at least {rule.min_account_age_days} days old (currently {account_age_days}).")

    income_proxy = get_income_proxy(account)
    reference_emi = calculate_emi(amount, rule.reference_annual_rate, tenure_months)
    existing_emi_total = Loan.objects.filter(customer=customer, status="APPROVED").aggregate(
        total=Sum("emi_amount")
    )["total"] or Decimal("0")
    total_emi_burden = existing_emi_total + reference_emi

    if income_proxy <= 0:
        reasons.append("Insufficient deposit history on this account to estimate income.")
    else:
        dti = (total_emi_burden / income_proxy) * 100
        if dti > rule.max_debt_to_income_ratio:
            reasons.append(
                f"Estimated debt-to-income ratio ({dti:.1f}%) exceeds the allowed limit ({rule.max_debt_to_income_ratio}%)."
            )

    return (len(reasons) == 0, reasons)