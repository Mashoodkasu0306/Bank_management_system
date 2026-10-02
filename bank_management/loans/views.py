from decimal import Decimal, InvalidOperation
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db import transaction as db_transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from accounts.models import Account
from transactions.models import Transaction
from users.models import Employee
from bank.views import is_admin_or_employee
from .models import Loan, LoanRepayment, LoanDocument, validate_document_extension, validate_document_size
from .utils import generate_amortization_schedule, check_eligibility
from services.helpers import require_verified_kyc, check_income_proof_for_loan
from services.forms import check_document_file
from notifications.helpers import notify, notify_staff
from audit.helpers import log_action
from audit.models import Actions

def is_employee(user):
    return user.is_authenticated and Employee.objects.filter(user=user).exists()


def _owns_loan(user, loan):
    return hasattr(user, "customer") and loan.customer_id == user.customer.id


@login_required
@require_verified_kyc
def apply_loan(request):
    if not hasattr(request.user, "customer"):
        messages.error(request, "Only customers can apply for loans.")
        return redirect("customer_dashboard")

    customer = request.user.customer
    accounts = Account.objects.filter(customer=customer, status="ACTIVE")

    has_income_proof, income_reason = check_income_proof_for_loan(customer.kyc_verification)
    if not has_income_proof:
        messages.error(request, income_reason)
        return redirect("kyc_dashboard")

    if request.method == "POST":
        loan_type = request.POST.get("loan_type")
        repayment_type = request.POST.get("repayment_type")
        amount_raw = request.POST.get("amount")
        tenure_raw = request.POST.get("tenure_months")
        account_id = request.POST.get("account")
        document_type = request.POST.get("document_type", "OTHER")
        uploaded_file = request.FILES.get("document")

        if repayment_type not in ("EMI", "LUMP_SUM"):
            messages.error(request, "Select a valid repayment type.")
            return redirect("apply_loan")

        account = accounts.filter(id=account_id).first()
        if not account:
            messages.error(request, "Select a valid account of yours for disbursement.")
            return redirect("apply_loan")

        try:
            amount = Decimal(amount_raw)
            tenure_months = int(tenure_raw)
        except (InvalidOperation, ValueError, TypeError):
            messages.error(request, "Invalid amount or tenure.")
            return redirect("apply_loan")

        if amount <= 0 or tenure_months <= 0:
            messages.error(request, "Amount and tenure must be greater than zero.")
            return redirect("apply_loan")

        if uploaded_file:
            try:
                validate_document_extension(uploaded_file)
                validate_document_size(uploaded_file)
                check_document_file(uploaded_file)
            except ValidationError as e:
                messages.error(request, "; ".join(e.messages))
                return redirect("apply_loan")

        is_eligible, reasons = check_eligibility(customer, account, loan_type, amount, tenure_months)
        if not is_eligible:
            for reason in reasons:
                messages.error(request, reason)
            messages.error(request, "You do not currently meet the eligibility criteria for this loan.")
            return redirect("apply_loan")

        with db_transaction.atomic():
            loan = Loan.objects.create(
                customer=customer,
                account=account,
                loan_type=loan_type,
                repayment_type=repayment_type,
                amount=amount,
                tenure_months=tenure_months,
            )
            if uploaded_file:
                LoanDocument.objects.create(loan=loan, document_type=document_type, file=uploaded_file)

        notify_staff(
            "LOAN",
            "New loan application",
            f"{request.user.username} applied for a {loan.get_loan_type_display()} of {amount} ({tenure_months} months).",
            link="/loans/pending/"
        )

        log_action(
            Actions.LOAN_APPLIED, request=request,
            target_type="LOAN", target_id=loan.id,
            details=f"{loan.get_loan_type_display()} of {amount} for {tenure_months} months ({loan.get_repayment_type_display()})",
        )
        messages.success(request, "Loan application submitted. Awaiting approval.")
        return redirect("loan_detail", loan_id=loan.id)

    return render(request, "loans/apply_loan.html", {"accounts": accounts})


@login_required
def upload_loan_document(request, loan_id):
    loan = get_object_or_404(Loan, id=loan_id)

    if not _owns_loan(request.user, loan):
        messages.error(request, "You do not have permission to modify this loan.")
        return redirect("login")

    if loan.status != "PENDING":
        messages.error(request, "Documents can only be added while the loan is pending review.")
        return redirect("loan_detail", loan_id=loan.id)

    if request.method == "POST":
        document_type = request.POST.get("document_type", "OTHER")
        uploaded_file = request.FILES.get("document")

        if not uploaded_file:
            messages.error(request, "Select a file to upload.")
            return redirect("loan_detail", loan_id=loan.id)

        try:
            validate_document_extension(uploaded_file)
            validate_document_size(uploaded_file)
            check_document_file(uploaded_file)
        except ValidationError as e:
            messages.error(request, "; ".join(e.messages))
            return redirect("loan_detail", loan_id=loan.id)

        LoanDocument.objects.create(loan=loan, document_type=document_type, file=uploaded_file)
        messages.success(request, "Document uploaded.")

    return redirect("loan_detail", loan_id=loan.id)


@login_required
def my_loans(request):
    if not hasattr(request.user, "customer"):
        messages.error(request, "Only customers can view their loans here.")
        return redirect("customer_dashboard")

    loans = Loan.objects.filter(customer=request.user.customer).order_by("-applied_date")
    for loan in loans:
        loan.refresh_default_status()
    return render(request, "loans/my_loans.html", {"loans": loans})


@login_required
def loan_detail(request, loan_id):
    loan = get_object_or_404(Loan, id=loan_id)

    is_owner = _owns_loan(request.user, loan)
    if not (is_owner or is_admin_or_employee(request.user)):
        messages.error(request, "You do not have permission to view this loan.")
        return redirect("login")

    loan.refresh_default_status()

    repayments = loan.repayments.all()
    documents = loan.documents.all()

    foreclosure_preview = None
    if loan.status == "APPROVED" and loan.repayment_type == "EMI" and loan.foreclosure_status == "NONE":
        outstanding_principal, accrued_interest = loan.get_foreclosure_amount()
        foreclosure_preview = {
            "outstanding_principal": outstanding_principal,
            "accrued_interest": accrued_interest,
            "total": outstanding_principal + accrued_interest,
        }

    my_accounts = None
    if is_owner and loan.repayment_type == "LUMP_SUM" and loan.status == "APPROVED":
        my_accounts = Account.objects.filter(customer=request.user.customer, status="ACTIVE")

    return render(request, "loans/loan_detail.html", {
        "loan": loan,
        "repayments": repayments,
        "documents": documents,
        "is_owner": is_owner,
        "is_staff_viewer": is_admin_or_employee(request.user),
        "foreclosure_preview": foreclosure_preview,
        "my_accounts": my_accounts,
    })


@login_required
@user_passes_test(is_admin_or_employee)
def pending_loans(request):
    loans = Loan.objects.filter(status="PENDING").select_related("customer__user", "account").order_by("applied_date")
    return render(request, "loans/pending_loans.html", {"loans": loans})


@login_required
@user_passes_test(is_admin_or_employee)
def all_loans(request):
    status_filter = request.GET.get("status", "all")
    loans = Loan.objects.select_related("customer__user", "account").order_by("-applied_date")

    for loan in loans:
        loan.refresh_default_status()

    if status_filter != "all":
        loans = loans.filter(status=status_filter.upper())

    return render(request, "loans/all_loans.html", {"loans": loans, "status_filter": status_filter})


@login_required
@user_passes_test(is_admin_or_employee)
def defaulted_loans(request):
    loans = Loan.objects.filter(status="APPROVED").select_related("customer__user", "account")
    for loan in loans:
        loan.refresh_default_status()
    defaulted = Loan.objects.filter(status="DEFAULTED").select_related("customer__user", "account")
    return render(request, "loans/defaulted_loans.html", {"loans": defaulted})


@login_required
@user_passes_test(is_admin_or_employee)
def approve_loan(request, loan_id):
    loan = get_object_or_404(Loan, id=loan_id, status="PENDING")

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "reject":
            loan.status = "REJECTED"
            loan.remarks = request.POST.get("remarks", "")
            loan.approved_by = request.user
            loan.approved_date = timezone.now()
            loan.save()

            notify(
                loan.customer.user, "LOAN",
                "Loan application rejected",
                f"Your {loan.get_loan_type_display()} application for {loan.amount} was rejected. Reason: {loan.remarks}",
                link=f"/loans/{loan.id}/"
            )

            log_action(
                Actions.LOAN_REJECTED, request=request,
                target_type="LOAN", target_id=loan.id,
                details=f"{loan.get_loan_type_display()} of {loan.amount} for {loan.customer.user.username} - reason: {loan.remarks}",
            )

            messages.success(request, "Loan rejected.")
            return redirect("pending_loans")

        elif action == "approve":
            rate_raw = request.POST.get("interest_rate")
            try:
                interest_rate = Decimal(rate_raw)
            except InvalidOperation:
                messages.error(request, "Invalid interest rate.")
                return redirect("approve_loan", loan_id=loan.id)

            if interest_rate < 0:
                messages.error(request, "Interest rate cannot be negative.")
                return redirect("approve_loan", loan_id=loan.id)

            is_renewal = loan.renewed_from_id is not None

            with db_transaction.atomic():
                account = Account.objects.select_for_update().get(id=loan.account_id, status="ACTIVE")

                if not is_renewal:
                    account.balance += loan.amount
                    account.save()

                    Transaction.objects.create(
                        transaction_type="DEPOSIT",
                        to_account=account,
                        amount=loan.amount,
                        mode_of_transaction="NETBANKING",
                        status="SUCCESS",
                        performed_by=request.user,
                        remarks=f"Loan disbursement - {loan.get_loan_type_display()} (Loan #{loan.id})",
                        is_loan_related=True,
                    )

                loan.interest_rate = interest_rate
                loan.status = "APPROVED"
                loan.approved_by = request.user
                loan.approved_date = timezone.now()

                if loan.repayment_type == "EMI":
                    schedule = generate_amortization_schedule(
                        loan.amount, interest_rate, loan.tenure_months, timezone.localdate()
                    )
                    loan.emi_amount = schedule[0]["emi_amount"]
                    loan.save()

                    for row in schedule:
                        LoanRepayment.objects.create(
                            loan=loan,
                            installment_number=row["installment_number"],
                            due_date=row["due_date"],
                            emi_amount=row["emi_amount"],
                            principal_component=row["principal_component"],
                            interest_component=row["interest_component"],
                            closing_balance=row["closing_balance"],
                        )
                else:
                    loan.lump_sum_total_payable = (loan.amount * (1 + interest_rate / Decimal(100))).quantize(
                        Decimal("0.01")
                    )
                    loan.save()

            notify(
                loan.customer.user, "LOAN",
                "Loan approved",
                f"Your {loan.get_loan_type_display()} of {loan.amount} was approved at {interest_rate}% interest.",
                link=f"/loans/{loan.id}/"
            )

            log_action(
                Actions.LOAN_APPROVED, request=request,
                target_type="LOAN", target_id=loan.id,
                details=(
                    f"{loan.get_loan_type_display()} of {loan.amount} for {loan.customer.user.username} at {interest_rate}%"
                    + (" (renewal)" if is_renewal else "")
                ),
            )

            if not is_renewal:
                messages.success(request, f"Loan approved and disbursed to {account.account_no}.")
            else:
                messages.success(request, "Renewal loan approved (no new cash disbursed - this restructures the prior debt).")
            return redirect("pending_loans")

    return render(request, "loans/approve_loan.html", {"loan": loan})


@login_required
def pay_emi(request, repayment_id):
    repayment = get_object_or_404(LoanRepayment, id=repayment_id, status="PENDING")
    loan = repayment.loan

    if not _owns_loan(request.user, loan):
        messages.error(request, "You can only pay your own loan installments.")
        return redirect("login")

    if request.method == "POST":
        with db_transaction.atomic():
            account = Account.objects.select_for_update().get(id=loan.account_id, status="ACTIVE")

            if account.balance < repayment.emi_amount:
                messages.error(request, "Insufficient balance to pay this EMI.")
                return redirect("loan_detail", loan_id=loan.id)

            account.balance -= repayment.emi_amount
            account.save()

            Transaction.objects.create(
                transaction_type="WITHDRAW",
                from_account=account,
                amount=repayment.emi_amount,
                mode_of_transaction="NETBANKING",
                status="SUCCESS",
                performed_by=request.user,
                remarks=f"EMI payment - Loan #{loan.id}, Installment {repayment.installment_number}",
                is_loan_related=True,
            )

            repayment.status = "PAID"
            repayment.paid_date = timezone.now()
            repayment.save()

            if not loan.repayments.filter(status="PENDING").exists():
                loan.status = "CLOSED"
                loan.save()

        log_action(
            Actions.EMI_PAID, request=request,
            target_type="LOAN", target_id=loan.id,
            details=f"Installment {repayment.installment_number} of {repayment.emi_amount} paid",
        )
        messages.success(request, f"EMI of {repayment.emi_amount} paid successfully.")
    return redirect("loan_detail", loan_id=loan.id)


@login_required
def pay_lump_sum(request, loan_id):
    """Step 1: collect amount, account, mode, (optional UPI ID) - then show a
    confirmation screen before anything is actually debited."""
    loan = get_object_or_404(Loan, id=loan_id, status="APPROVED", repayment_type="LUMP_SUM")

    if not _owns_loan(request.user, loan):
        messages.error(request, "You can only pay your own loans.")
        return redirect("login")

    my_accounts = Account.objects.filter(customer=request.user.customer, status="ACTIVE")

    if request.method == "POST":
        amount_raw = request.POST.get("amount")
        account_id = request.POST.get("account")
        mode = request.POST.get("mode_of_transaction", "NETBANKING")
        upi_id = request.POST.get("upi_id", "").strip()

        try:
            amount = Decimal(amount_raw)
        except InvalidOperation:
            messages.error(request, "Invalid amount.")
            return redirect("loan_detail", loan_id=loan.id)

        remaining = loan.get_lump_sum_remaining()

        if amount <= 0:
            messages.error(request, "Amount must be greater than zero.")
            return redirect("loan_detail", loan_id=loan.id)

        if amount > remaining:
            messages.error(request, f"Amount exceeds the remaining balance of {remaining}.")
            return redirect("loan_detail", loan_id=loan.id)

        if mode == "UPI":
            if not upi_id:
                messages.error(request, "Enter a UPI ID.")
                return redirect("loan_detail", loan_id=loan.id)
            # No explicit account chosen for UPI - auto-pick one of the
            # customer's own accounts with enough balance (UPI is just a
            # thin layer over a real bank account in practice).
            pay_account = my_accounts.filter(balance__gte=amount).order_by("-balance").first()
            if not pay_account:
                pay_account = my_accounts.order_by("-balance").first()
            if not pay_account:
                messages.error(request, "You have no active account to pay from.")
                return redirect("loan_detail", loan_id=loan.id)
        else:
            pay_account = my_accounts.filter(id=account_id).first()
            if not pay_account:
                messages.error(request, "Select a valid account of yours to pay from.")
                return redirect("loan_detail", loan_id=loan.id)

        return render(request, "loans/confirm_lump_sum_payment.html", {
            "loan": loan,
            "amount": amount,
            "account": pay_account,
            "mode": mode,
            "upi_id": upi_id,
        })

    return redirect("loan_detail", loan_id=loan.id)


@login_required
def confirm_pay_lump_sum(request, loan_id):
    """Step 2: the actual debit happens only here, after explicit confirmation."""
    loan = get_object_or_404(Loan, id=loan_id, status="APPROVED", repayment_type="LUMP_SUM")

    if not _owns_loan(request.user, loan):
        messages.error(request, "You can only pay your own loans.")
        return redirect("login")

    if request.method != "POST":
        return redirect("loan_detail", loan_id=loan.id)

    amount_raw = request.POST.get("amount")
    account_id = request.POST.get("account")
    mode = request.POST.get("mode_of_transaction", "NETBANKING")
    upi_id = request.POST.get("upi_id", "").strip()

    my_accounts = Account.objects.filter(customer=request.user.customer, status="ACTIVE")
    pay_account = my_accounts.filter(id=account_id).first()

    if not pay_account:
        messages.error(request, "Select a valid account of yours to pay from.")
        return redirect("loan_detail", loan_id=loan.id)

    try:
        amount = Decimal(amount_raw)
    except InvalidOperation:
        messages.error(request, "Invalid amount.")
        return redirect("loan_detail", loan_id=loan.id)

    remaining = loan.get_lump_sum_remaining()
    if amount <= 0 or amount > remaining:
        messages.error(request, "Invalid amount for this payment.")
        return redirect("loan_detail", loan_id=loan.id)

    with db_transaction.atomic():
        account = Account.objects.select_for_update().get(id=pay_account.id, status="ACTIVE")

        if account.balance < amount:
            messages.error(request, "Insufficient balance for this payment.")
            return redirect("loan_detail", loan_id=loan.id)

        account.balance -= amount
        account.save()

        remarks = f"Lump sum loan repayment - Loan #{loan.id}"
        if mode == "UPI" and upi_id:
            remarks += f" (UPI: {upi_id})"

        Transaction.objects.create(
            transaction_type="WITHDRAW",
            from_account=account,
            amount=amount,
            mode_of_transaction=mode,
            status="SUCCESS",
            performed_by=request.user,
            remarks=remarks,
            is_loan_related=True,
        )

        loan.lump_sum_paid += amount
        if loan.lump_sum_paid >= loan.lump_sum_total_payable:
            loan.status = "CLOSED"
        loan.save()
        log_action(
            Actions.LUMP_SUM_PAID, request=request,
            target_type="LOAN", target_id=loan.id,
            details=f"Paid {amount} from account {account.account_no} via {mode}",
        )
        messages.success(request, f"Payment of {amount} successful. Remaining balance: {loan.get_lump_sum_remaining()}")
    return redirect("loan_detail", loan_id=loan.id)


@login_required
def request_foreclosure(request, loan_id):
      
    loan = get_object_or_404(Loan, id=loan_id, status="APPROVED", repayment_type="EMI")

    if not _owns_loan(request.user, loan):
        messages.error(request, "You do not have permission to modify this loan.")
        return redirect("login")

    if loan.foreclosure_status != "NONE":
        messages.error(request, "A foreclosure request already exists for this loan.")
        return redirect("loan_detail", loan_id=loan.id)

    if request.method == "POST":
        loan.foreclosure_status = "REQUESTED"
        loan.foreclosure_requested_date = timezone.now()
        loan.save()
        log_action(
            Actions.FORECLOSURE_REQUESTED, request=request,
            target_type="LOAN", target_id=loan.id,
            details=f"Foreclosure requested for loan #{loan.id}",
        )
        messages.success(request, "Foreclosure request submitted. Awaiting bank approval.")

    return redirect("loan_detail", loan_id=loan.id)


@login_required
@user_passes_test(is_admin_or_employee)
def pending_foreclosures(request):
    loans = Loan.objects.filter(foreclosure_status="REQUESTED").select_related("customer__user", "account")
    return render(request, "loans/pending_foreclosures.html", {"loans": loans})


@login_required
@user_passes_test(is_admin_or_employee)
def process_foreclosure(request, loan_id):
    loan = get_object_or_404(Loan, id=loan_id, foreclosure_status="REQUESTED")

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "reject":
            loan.foreclosure_status = "REJECTED"
            loan.save()
            notify(
                loan.customer.user, "LOAN",
                "Foreclosure request rejected",
                f"Your foreclosure request for loan #{loan.id} was rejected.",
                link=f"/loans/{loan.id}/"
            )
            log_action(
                Actions.FORECLOSURE_REJECTED, request=request,
                target_type="LOAN", target_id=loan.id,
                details=f"Foreclosure request for {loan.customer.user.username} rejected",
            )
            messages.success(request, "Foreclosure request rejected.")
            return redirect("pending_foreclosures")

        elif action == "approve":
            outstanding_principal, accrued_interest = loan.get_foreclosure_amount()
            total_due = outstanding_principal + accrued_interest

            with db_transaction.atomic():
                account = Account.objects.select_for_update().get(id=loan.account_id, status="ACTIVE")

                if account.balance < total_due:
                    messages.error(request, f"Customer's account balance ({account.balance}) is insufficient to cover the foreclosure amount ({total_due}).")
                    return redirect("pending_foreclosures")

                account.balance -= total_due
                account.save()

                Transaction.objects.create(
                    transaction_type="WITHDRAW",
                    from_account=account,
                    amount=total_due,
                    mode_of_transaction="NETBANKING",
                    status="SUCCESS",
                    performed_by=request.user,
                    remarks=f"Loan foreclosure - Loan #{loan.id} (principal {outstanding_principal} + interest {accrued_interest})",
                    is_loan_related=True,
                )

                loan.repayments.filter(status="PENDING").update(status="WAIVED")
                loan.status = "CLOSED"
                loan.foreclosure_status = "APPROVED"
                loan.save()

            notify(
                loan.customer.user, "LOAN",
                "Foreclosure approved",
                f"Your loan #{loan.id} was foreclosed. {total_due} was debited from account {account.account_no}.",
                link=f"/loans/{loan.id}/"
            )
            log_action(
                Actions.FORECLOSURE_APPROVED, request=request,
                target_type="LOAN", target_id=loan.id,
                details=f"Loan for {loan.customer.user.username} foreclosed, {total_due} debited from {account.account_no}",
            )
            messages.success(request, f"Loan #{loan.id} foreclosed. {total_due} debited from {account.account_no}.")
            return redirect("pending_foreclosures")

    outstanding_principal, accrued_interest = loan.get_foreclosure_amount()
    return render(request, "loans/process_foreclosure.html", {
        "loan": loan,
        "outstanding_principal": outstanding_principal,
        "accrued_interest": accrued_interest,
        "total": outstanding_principal + accrued_interest,
    })


@login_required
@user_passes_test(is_admin_or_employee)
def renew_loan(request, loan_id):
    original = get_object_or_404(Loan, id=loan_id, status="DEFAULTED")

    remaining_amount = original.get_remaining_amount()
    fee = (remaining_amount * Decimal("0.02")).quantize(Decimal("0.01"))
    total_new_amount = remaining_amount + fee

    if request.method == "POST":
        tenure_raw = request.POST.get("tenure_months")
        try:
            tenure_months = int(tenure_raw)
        except (ValueError, TypeError):
            messages.error(request, "Invalid tenure.")
            return redirect("renew_loan", loan_id=original.id)

        if tenure_months <= 0:
            messages.error(request, "Tenure must be greater than zero.")
            return redirect("renew_loan", loan_id=original.id)

        with db_transaction.atomic():
            new_loan = Loan.objects.create(
                customer=original.customer,
                account=original.account,
                loan_type=original.loan_type,
                repayment_type=original.repayment_type,
                amount=total_new_amount,
                tenure_months=tenure_months,
                renewed_from=original,
                renewal_fee=fee,
            )
            original.status = "RENEWED"
            original.save()

        log_action(
            Actions.LOAN_RENEWED, request=request,
            target_type="LOAN", target_id=original.id,
            details=f"Renewed as loan #{new_loan.id} for {total_new_amount} (fee {fee}), customer {original.customer.user.username}",
        )
        messages.success(request, f"Renewal loan #{new_loan.id} created for {total_new_amount} (includes {fee} renewal fee). Proceed to approve it.")
        return redirect("approve_loan", loan_id=new_loan.id)

    return render(request, "loans/renew_loan.html", {
        "loan": original,
        "remaining_amount": remaining_amount,
        "fee": fee,
        "total_new_amount": total_new_amount,
    })