from django.db.models import Q, Sum
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db import transaction as db_transaction
from django.utils import timezone
from decimal import Decimal, InvalidOperation

from accounts.models import Account
from .models import Transaction
from users.models import Employee, Customer
from bank.views import is_admin_or_employee


def is_employee(user):
    return user.is_authenticated and Employee.objects.filter(user=user).exists()


def is_admin_user(user):
    if not user.is_authenticated:
        return False
    if Customer.objects.filter(user=user).exists():
        return False
    if Employee.objects.filter(user=user).exists():
        return False
    return True


def can_view_account(user, account):
    if is_admin_user(user):
        return True
    if Employee.objects.filter(user=user).exists():
        return True
    if hasattr(user, "customer") and account.customer_id == user.customer.id:
        return True
    return False


def get_today_transacted_amount(account, transaction_type):
    today = timezone.localdate()
    if transaction_type == "DEPOSIT":
        qs = Transaction.objects.filter(
            to_account=account, transaction_type="DEPOSIT", status="SUCCESS", timestamp__date=today
        )
    else:
        qs = Transaction.objects.filter(
            from_account=account, transaction_type="WITHDRAW", status="SUCCESS", timestamp__date=today
        )
    return qs.aggregate(total=Sum("amount"))["total"] or Decimal("0")


def get_today_debit_total(account):
    """Combines withdrawals and outgoing transfers - both are debits against the account's
    daily limit. Loan-related transactions (disbursements, EMI, lump sum, foreclosure) are
    excluded, since they're bank-approved events, not ordinary teller/self-service activity."""
    today = timezone.localdate()
    qs = Transaction.objects.filter(
        from_account=account,
        transaction_type__in=["WITHDRAW", "TRANSFER"],
        status="SUCCESS",
        timestamp__date=today,
        is_loan_related=False,
    )
    return qs.aggregate(total=Sum("amount"))["total"] or Decimal("0")


@login_required
@user_passes_test(is_employee)
def deposit_view(request):
    if request.method == "POST":
        account_no = request.POST["account_no"]
        amount_raw = request.POST["amount"]

        try:
            amount = Decimal(amount_raw)
        except InvalidOperation:
            messages.error(request, "Invalid amount.")
            return redirect("deposit")

        if amount <= 0:
            messages.error(request, "Amount must be greater than zero.")
            return redirect("deposit")

        try:
            with db_transaction.atomic():
                account = Account.objects.select_for_update().get(account_no=account_no, status="ACTIVE")

                today_total = get_today_transacted_amount(account, "DEPOSIT")
                if today_total + amount > account.daily_limit:
                    Transaction.objects.create(
                        transaction_type="DEPOSIT",
                        to_account=account,
                        amount=amount,
                        mode_of_transaction=request.POST.get("mode_of_transaction", "CASH"),
                        status="PENDING",
                        performed_by=request.user,
                        remarks=f"Exceeds daily limit ({account.daily_limit}); awaiting approval",
                    )
                    messages.error(request, f"This deposit exceeds the account's daily limit of {account.daily_limit}. Sent for approval.")
                    return redirect("deposit")

                account.balance += amount
                account.save()

                Transaction.objects.create(
                    transaction_type="DEPOSIT",
                    to_account=account,
                    amount=amount,
                    mode_of_transaction=request.POST.get("mode_of_transaction", "CASH"),
                    status="SUCCESS",
                    performed_by=request.user,
                    remarks=f"Deposit to {account.account_no}",
                )
            messages.success(request, f"Deposited {amount} to {account_no}. New balance: {account.balance}")
            return redirect("deposit")
        except Account.DoesNotExist:
            messages.error(request, "Account not found or not active.")
            return redirect("deposit")

    return render(request, "transactions/deposit.html")


@login_required
@user_passes_test(is_employee)
def withdraw_view(request):
    if request.method == "POST":
        account_no = request.POST["account_no"]
        amount_raw = request.POST["amount"]

        try:
            amount = Decimal(amount_raw)
        except InvalidOperation:
            messages.error(request, "Invalid amount.")
            return redirect("withdraw")

        if amount <= 0:
            messages.error(request, "Amount must be greater than zero.")
            return redirect("withdraw")

        try:
            with db_transaction.atomic():
                account = Account.objects.select_for_update().get(account_no=account_no, status="ACTIVE")

                today_total = get_today_debit_total(account)
                if today_total + amount > account.daily_limit:
                    Transaction.objects.create(
                        transaction_type="WITHDRAW",
                        from_account=account,
                        amount=amount,
                        mode_of_transaction=request.POST.get("mode_of_transaction", "CASH"),
                        status="PENDING",
                        performed_by=request.user,
                        remarks=f"Exceeds daily limit ({account.daily_limit}); awaiting approval",
                    )
                    messages.error(request, f"This withdrawal exceeds the account's daily limit of {account.daily_limit}. Sent for approval.")
                    return redirect("withdraw")

                if account.balance < amount:
                    Transaction.objects.create(
                        transaction_type="WITHDRAW",
                        from_account=account,
                        amount=amount,
                        mode_of_transaction=request.POST.get("mode_of_transaction", "CASH"),
                        status="FAILED",
                        performed_by=request.user,
                        remarks="Insufficient balance",
                    )
                    messages.error(request, "Insufficient balance.")
                    return redirect("withdraw")

                account.balance -= amount
                account.save()

                Transaction.objects.create(
                    transaction_type="WITHDRAW",
                    from_account=account,
                    amount=amount,
                    mode_of_transaction=request.POST.get("mode_of_transaction", "CASH"),
                    status="SUCCESS",
                    performed_by=request.user,
                    remarks=f"Withdrawal from {account.account_no}",
                )
            messages.success(request, f"Withdrew {amount} from {account_no}. New balance: {account.balance}")
            return redirect("withdraw")
        except Account.DoesNotExist:
            messages.error(request, "Account not found or not active.")
            return redirect("withdraw")

    return render(request, "transactions/withdraw.html")


@login_required
@user_passes_test(is_employee)
def transfer_view(request):
    if request.method == "POST":
        from_no = request.POST["from_account_no"]
        to_no = request.POST["to_account_no"]
        amount_raw = request.POST["amount"]

        if from_no == to_no:
            messages.error(request, "Cannot transfer to the same account.")
            return redirect("transfer")

        try:
            amount = Decimal(amount_raw)
        except InvalidOperation:
            messages.error(request, "Invalid amount.")
            return redirect("transfer")

        if amount <= 0:
            messages.error(request, "Amount must be greater than zero.")
            return redirect("transfer")

        try:
            with db_transaction.atomic():
                accounts = Account.objects.select_for_update().filter(
                    account_no__in=[from_no, to_no], status="ACTIVE"
                ).order_by("account_no")

                accounts_by_no = {a.account_no: a for a in accounts}
                from_account = accounts_by_no.get(from_no)
                to_account = accounts_by_no.get(to_no)

                if not from_account or not to_account:
                    messages.error(request, "One or both accounts not found or not active.")
                    return redirect("transfer")

                today_total = get_today_debit_total(from_account)
                if today_total + amount > from_account.daily_limit:
                    Transaction.objects.create(
                        transaction_type="TRANSFER",
                        from_account=from_account,
                        to_account=to_account,
                        amount=amount,
                        mode_of_transaction=request.POST.get("mode_of_transaction", "NETBANKING"),
                        status="PENDING",
                        performed_by=request.user,
                        remarks=f"Exceeds daily limit ({from_account.daily_limit}); awaiting approval",
                    )
                    messages.error(request, f"This transfer exceeds the source account's daily limit of {from_account.daily_limit}. Sent for approval.")
                    return redirect("transfer")

                if from_account.balance < amount:
                    Transaction.objects.create(
                        transaction_type="TRANSFER",
                        from_account=from_account,
                        to_account=to_account,
                        amount=amount,
                        mode_of_transaction=request.POST.get("mode_of_transaction", "NETBANKING"),
                        status="FAILED",
                        performed_by=request.user,
                        remarks="Insufficient balance",
                    )
                    messages.error(request, "Insufficient balance in source account.")
                    return redirect("transfer")

                from_account.balance -= amount
                to_account.balance += amount
                from_account.save()
                to_account.save()

                Transaction.objects.create(
                    transaction_type="TRANSFER",
                    from_account=from_account,
                    to_account=to_account,
                    amount=amount,
                    mode_of_transaction=request.POST.get("mode_of_transaction", "NETBANKING"),
                    status="SUCCESS",
                    performed_by=request.user,
                    remarks=f"Transfer {from_no} -> {to_no}",
                )
            messages.success(request, f"Transferred {amount} from {from_no} to {to_no}.")
            return redirect("transfer")
        except Account.DoesNotExist:
            messages.error(request, "One or both accounts not found.")
            return redirect("transfer")

    return render(request, "transactions/transfer.html")


@login_required
def transaction_history(request, account_id):
    account = get_object_or_404(Account, id=account_id)

    if not can_view_account(request.user, account):
        messages.error(request, "You do not have permission to view this account.")
        return redirect("login")

    txns = Transaction.objects.filter(
        Q(from_account=account) | Q(to_account=account)
    ).order_by("-timestamp")

    return render(request, "transactions/transaction_history.html", {"account": account, "transactions": txns})


@login_required
@user_passes_test(is_admin_user)
def all_transactions(request):
    filter_type = request.GET.get("filter", "all")

    txns = Transaction.objects.select_related(
        "from_account__customer__user", "to_account__customer__user", "performed_by"
    ).order_by("-timestamp")

    if filter_type == "employee":
        employee_user_ids = Employee.objects.values_list("user_id", flat=True)
        txns = txns.filter(performed_by_id__in=employee_user_ids)
    elif filter_type == "customer":
        customer_user_ids = Customer.objects.values_list("user_id", flat=True)
        txns = txns.filter(performed_by_id__in=customer_user_ids)

    return render(request, "transactions/all_transactions.html", {
        "transactions": txns,
        "filter_type": filter_type,
    })


@login_required
@user_passes_test(is_employee)
def my_transactions(request):
    txns = Transaction.objects.filter(performed_by=request.user).order_by("-timestamp")
    return render(request, "transactions/my_transactions.html", {"transactions": txns})


@login_required
def customer_transfer_view(request):
    if not hasattr(request.user, "customer"):
        messages.error(request, "Only customers can access self-service transfers.")
        return redirect("customer_dashboard")

    customer = request.user.customer
    my_accounts = Account.objects.filter(customer=customer, status="ACTIVE")

    if request.method == "POST":
        from_no = request.POST["from_account_no"]
        to_no = request.POST["to_account_no"]
        amount_raw = request.POST["amount"]

        if not my_accounts.filter(account_no=from_no).exists():
            messages.error(request, "You can only transfer from your own account.")
            return redirect("customer_transfer")

        try:
            amount = Decimal(amount_raw)
        except InvalidOperation:
            messages.error(request, "Invalid amount.")
            return redirect("customer_transfer")

        if amount <= 0:
            messages.error(request, "Amount must be greater than zero.")
            return redirect("customer_transfer")

        if from_no == to_no:
            same_account = my_accounts.filter(account_no=from_no).first()
            Transaction.objects.create(
                transaction_type="TRANSFER",
                from_account=same_account,
                to_account=same_account,
                amount=amount,
                mode_of_transaction=request.POST.get("mode_of_transaction", "NETBANKING"),
                status="FAILED",
                performed_by=request.user,
                remarks="Attempted transfer to same account",
            )
            messages.error(request, "Cannot transfer to the same account.")
            return redirect("customer_transfer")

        try:
            with db_transaction.atomic():
                accounts = Account.objects.select_for_update().filter(
                    account_no__in=[from_no, to_no], status="ACTIVE"
                ).order_by("account_no")

                accounts_by_no = {a.account_no: a for a in accounts}
                from_account = accounts_by_no.get(from_no)
                to_account = accounts_by_no.get(to_no)

                if not from_account or not to_account:
                    messages.error(request, "One or both accounts not found or not active.")
                    return redirect("customer_transfer")

                today_total = get_today_debit_total(from_account)
                if today_total + amount > from_account.daily_limit:
                    Transaction.objects.create(
                        transaction_type="TRANSFER",
                        from_account=from_account,
                        to_account=to_account,
                        amount=amount,
                        mode_of_transaction=request.POST.get("mode_of_transaction", "NETBANKING"),
                        status="PENDING",
                        performed_by=request.user,
                        remarks=f"Exceeds daily limit ({from_account.daily_limit}); awaiting approval",
                    )
                    messages.error(request, f"This transfer exceeds your account's daily limit of {from_account.daily_limit}. Sent for approval.")
                    return redirect("customer_transfer")

                if from_account.balance < amount:
                    Transaction.objects.create(
                        transaction_type="TRANSFER",
                        from_account=from_account,
                        to_account=to_account,
                        amount=amount,
                        mode_of_transaction=request.POST.get("mode_of_transaction", "NETBANKING"),
                        status="FAILED",
                        performed_by=request.user,
                        remarks="Insufficient balance (self-service transfer)",
                    )
                    messages.error(request, "Insufficient balance in your account.")
                    return redirect("customer_transfer")

                from_account.balance -= amount
                to_account.balance += amount
                from_account.save()
                to_account.save()

                Transaction.objects.create(
                    transaction_type="TRANSFER",
                    from_account=from_account,
                    to_account=to_account,
                    amount=amount,
                    mode_of_transaction=request.POST.get("mode_of_transaction", "NETBANKING"),
                    status="SUCCESS",
                    performed_by=request.user,
                    remarks=f"Self-service transfer {from_no} -> {to_no}",
                )
            messages.success(request, f"Transferred {amount} from {from_no} to {to_no}.")
            return redirect("customer_transfer")
        except Account.DoesNotExist:
            messages.error(request, "One or both accounts not found.")
            return redirect("customer_transfer")

    return render(request, "transactions/customer_transfer.html", {"accounts": my_accounts})


@login_required
def customer_search_transactions(request):
    if not hasattr(request.user, "customer"):
        messages.error(request, "Only customers can use this search.")
        return redirect("customer_dashboard")

    account_no = request.GET.get("account_no", "").strip()
    account = None
    txns = None

    if account_no:
        account = Account.objects.filter(account_no=account_no, customer=request.user.customer).first()
        if not account:
            messages.error(request, "No account with that number found under your profile.")
        else:
            txns = Transaction.objects.filter(
                Q(from_account=account) | Q(to_account=account)
            ).order_by("-timestamp")

    return render(request, "transactions/search_transactions.html", {
        "account": account,
        "transactions": txns,
        "account_no": account_no,
    })


@login_required
@user_passes_test(is_employee)
def employee_search_customer_transactions(request):
    account_no = request.GET.get("account_no", "").strip()
    account = None
    txns = None

    if account_no:
        account = Account.objects.filter(account_no=account_no).first()
        if not account:
            messages.error(request, "No account found with that number.")
        else:
            txns = Transaction.objects.filter(
                Q(from_account=account) | Q(to_account=account)
            ).order_by("-timestamp")

    return render(request, "transactions/employee_search_transactions.html", {
        "account": account,
        "transactions": txns,
        "account_no": account_no,
    })


@login_required
@user_passes_test(is_admin_or_employee)
def pending_transactions(request):
    account_no = request.GET.get("account_no", "").strip()

    txns = Transaction.objects.filter(status="PENDING").select_related(
        "from_account__customer__user", "to_account__customer__user", "performed_by"
    ).order_by("-timestamp")

    if account_no:
        txns = txns.filter(
            Q(from_account__account_no__icontains=account_no) |
            Q(to_account__account_no__icontains=account_no)
        )

    return render(request, "transactions/pending_transactions.html", {
        "transactions": txns,
        "account_no": account_no,
    })


@login_required
@user_passes_test(is_admin_or_employee)
def approve_transaction(request, txn_id):
    if request.method == "POST":
        action = request.POST.get("action")

        with db_transaction.atomic():
            txn = get_object_or_404(Transaction.objects.select_for_update(), id=txn_id, status="PENDING")

            if action == "approve":
                if txn.transaction_type == "DEPOSIT":
                    account = Account.objects.select_for_update().get(id=txn.to_account_id)
                    if account.status != "ACTIVE":
                        txn.status = "FAILED"
                        txn.remarks = f"{txn.remarks} | Rejected - account no longer active"
                        txn.save()
                        messages.error(request, "Cannot approve - account is no longer active.")
                    else:
                        account.balance += txn.amount
                        account.save()
                        txn.status = "SUCCESS"
                        txn.remarks = f"{txn.remarks} | Approved by {request.user.username}"
                        txn.save()
                        messages.success(request, f"Deposit of {txn.amount} approved.")

                elif txn.transaction_type == "WITHDRAW":
                    account = Account.objects.select_for_update().get(id=txn.from_account_id)
                    if account.status != "ACTIVE":
                        txn.status = "FAILED"
                        txn.remarks = f"{txn.remarks} | Rejected - account no longer active"
                        txn.save()
                        messages.error(request, "Cannot approve - account is no longer active.")
                    elif account.balance < txn.amount:
                        txn.status = "FAILED"
                        txn.remarks = f"{txn.remarks} | Rejected - insufficient balance at approval time"
                        txn.save()
                        messages.error(request, "Cannot approve - account no longer has sufficient balance.")
                    else:
                        account.balance -= txn.amount
                        account.save()
                        txn.status = "SUCCESS"
                        txn.remarks = f"{txn.remarks} | Approved by {request.user.username}"
                        txn.save()
                        messages.success(request, f"Withdrawal of {txn.amount} approved.")

                elif txn.transaction_type == "TRANSFER":
                    from_account = Account.objects.select_for_update().get(id=txn.from_account_id)
                    to_account = Account.objects.select_for_update().get(id=txn.to_account_id)
                    if from_account.status != "ACTIVE" or to_account.status != "ACTIVE":
                        txn.status = "FAILED"
                        txn.remarks = f"{txn.remarks} | Rejected - one or both accounts no longer active"
                        txn.save()
                        messages.error(request, "Cannot approve - one or both accounts are no longer active.")
                    elif from_account.balance < txn.amount:
                        txn.status = "FAILED"
                        txn.remarks = f"{txn.remarks} | Rejected - insufficient balance at approval time"
                        txn.save()
                        messages.error(request, "Cannot approve - source account no longer has sufficient balance.")
                    else:
                        from_account.balance -= txn.amount
                        to_account.balance += txn.amount
                        from_account.save()
                        to_account.save()
                        txn.status = "SUCCESS"
                        txn.remarks = f"{txn.remarks} | Approved by {request.user.username}"
                        txn.save()
                        messages.success(request, f"Transfer of {txn.amount} approved.")

            elif action == "reject":
                txn.status = "FAILED"
                txn.remarks = f"{txn.remarks} | Rejected by {request.user.username}"
                txn.save()
                messages.success(request, "Transaction rejected.")

        return redirect("pending_transactions")

    return redirect("pending_transactions")


@login_required
@user_passes_test(is_employee)
def branch_report(request):
    employee = request.user.employee
    if employee.branch is None:
        messages.error(request, "You are not assigned to a branch yet.")
        return redirect("employee_dashboard")

    branch = employee.branch
    accounts = Account.objects.filter(branch=branch)
    total_balance = accounts.aggregate(total=Sum("balance"))["total"] or 0
    branch_txn_filter = Q(from_account__branch=branch) | Q(to_account__branch=branch)
    recent_txns = Transaction.objects.filter(branch_txn_filter).order_by("-timestamp")[:50]
    total_transactions = Transaction.objects.filter(branch_txn_filter).count()

    context = {
        "branch": branch,
        "total_accounts": accounts.count(),
        "total_balance": total_balance,
        "total_transactions": total_transactions,
        "accounts": accounts,
        "recent_transactions": recent_txns,
    }
    return render(request, "transactions/branch_report.html", context)