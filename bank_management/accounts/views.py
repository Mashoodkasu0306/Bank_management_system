from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from bank.views import is_admin, is_admin_or_employee
from bank.models import Branch
from users.models import Customer
from .models import Account


@login_required
def create_account(request):
    user_is_admin = is_admin(request.user)
    employee = getattr(request.user, "employee", None)

    if not user_is_admin and not employee:
        messages.error(request, "Only branch employees or admin can open accounts.")
        return redirect("employee_dashboard")

    if employee and not user_is_admin and employee.branch is None:
        messages.error(request, "You are not assigned to a branch yet. Contact admin.")
        return redirect("employee_dashboard")

    customers = Customer.objects.filter(user__is_active=True)
    branches = Branch.objects.all() if user_is_admin else None

    if request.method == "POST":
        customer_id = request.POST.get("customer")
        account_type = request.POST.get("account_type")
        opening_balance = request.POST.get("balance") or 0

        customer = get_object_or_404(Customer, id=customer_id)

        if user_is_admin:
            branch_id = request.POST.get("branch")
            branch = get_object_or_404(Branch, id=branch_id)
        else:
            branch = employee.branch

        account = Account.objects.create(
            customer=customer,
            branch=branch,
            account_type=account_type,
            balance=opening_balance,
        )
        messages.success(request, f"Account {account.account_no} created for {customer.user.username}.")
        return redirect("account_list")

    return render(request, "accounts/create_account.html", {
        "customers": customers,
        "branches": branches,
        "is_admin": user_is_admin,
    })


@login_required
def account_list(request):
    if not is_admin_or_employee(request.user):
        messages.error(request, "You do not have permission to view accounts.")
        return redirect("customer_dashboard")

    accounts = Account.objects.select_related("customer__user", "branch").order_by("-open_date")
    return render(request, "accounts/account_list.html", {"accounts": accounts})


@login_required
def account_detail(request, account_id):
    account = get_object_or_404(Account, id=account_id)

    is_owner = hasattr(request.user, "customer") and account.customer == request.user.customer
    if not (is_owner or is_admin_or_employee(request.user)):
        messages.error(request, "You do not have permission to view this account.")
        return redirect("customer_dashboard")

    return render(request, "accounts/account_detail.html", {"account": account})