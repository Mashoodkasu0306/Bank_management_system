from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib import messages
from django.db.models import Sum
from django.db import transaction as db_transaction
from django.utils import timezone
from datetime import timedelta

from .models import Customer, Employee
from bank.views import is_admin, is_admin_or_employee
from bank.models import Bank, Branch
from accounts.models import Account
from transactions.models import Transaction


def user_login(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)

            # Role-based redirection
            if Customer.objects.filter(user=user).exists():
                return redirect("customer_dashboard")
            elif Employee.objects.filter(user=user).exists():
                return redirect("employee_dashboard")
            else:
                return redirect("admin_dashboard")
        else:
            messages.error(request, "Invalid username/password, or your account has been deactivated.")

    return render(request, "users/login.html")


def user_logout(request):
    logout(request)
    return redirect("login")


def home_redirect(request):
    if request.user.is_authenticated:
        if Customer.objects.filter(user=request.user).exists():
            return redirect("customer_dashboard")
        elif Employee.objects.filter(user=request.user).exists():
            return redirect("employee_dashboard")
        else:
            return redirect("admin_dashboard")
    return redirect("login")


@login_required
def customer_dashboard(request):
    if not hasattr(request.user, 'customer'):
        return redirect("login")

    from loans.models import LoanRepayment  # local import avoids circular import

    today = timezone.localdate()
    upcoming_cutoff = today + timedelta(days=7)

    due_reminders = LoanRepayment.objects.filter(
        loan__customer=request.user.customer,
        status="PENDING",
        due_date__lte=upcoming_cutoff,
    ).select_related("loan").order_by("due_date")

    return render(request, "users/customer_dashboard.html", {"due_reminders": due_reminders})


@login_required
def employee_dashboard(request):
    if not hasattr(request.user, 'employee'):
        return redirect("login")

    return render(request, "users/employee_dashboard.html")


def is_employee(user):
    return user.is_authenticated and Employee.objects.filter(user=user).exists()


@login_required
@user_passes_test(is_admin)
def admin_dashboard(request):
    total_balance = Account.objects.aggregate(total=Sum("balance"))["total"] or 0
    total_successful_volume = Transaction.objects.filter(status="SUCCESS").aggregate(total=Sum("amount"))["total"] or 0

    context = {
        "total_customers": Customer.objects.count(),
        "total_employees": Employee.objects.count(),
        "total_banks": Bank.objects.count(),
        "total_branches": Branch.objects.count(),
        "total_accounts": Account.objects.count(),
        "total_balance": total_balance,
        "total_transactions": Transaction.objects.count(),
        "total_successful_volume": total_successful_volume,
    }
    return render(request, "users/admin_dashboard.html", context)


@login_required
@user_passes_test(is_admin_or_employee)
def register_customer(request):
    if request.method == "POST":
        username = request.POST["username"]
        password = request.POST["password"]

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists.")
            return render(request, "users/register_customer.html")

        # Which branch gets the new account: staff use their own branch;
        # an admin (who has no branch) can choose one with a "branch" form field.
        employee = Employee.objects.filter(user=request.user).select_related("branch").first()
        branch = None
        if employee is not None:
            branch = employee.branch
        else:
            branch_id = request.POST.get("branch", "").strip()
            if branch_id.isdigit():
                branch = Branch.objects.filter(id=int(branch_id)).first()

        account_type = request.POST.get("account_type", "SAVINGS")
        if account_type not in ("SAVINGS", "CURRENT"):
            account_type = "SAVINGS"

        # All-or-nothing: the login, the customer and the account are
        # created together, or none of them are.
        with db_transaction.atomic():
            new_user = User.objects.create_user(username=username, password=password)

            customer = Customer.objects.create(
                user=new_user,
                customer_type=request.POST["customer_type"],
                dob=request.POST["dob"],
                gender=request.POST["gender"],
                address=request.POST["address"],
                kyc_status="PENDING",
            )

            account = None
            if branch is not None:
                account = Account.objects.create(
                    customer=customer, branch=branch,
                    account_type=account_type, status="ACTIVE",
                )

        if account is not None:
            messages.success(
                request,
                f"Customer {username} registered. {account.get_account_type_display()} "
                f"account {account.account_no} opened."
            )
        else:
            messages.warning(
                request,
                f"Customer {username} registered, but no account was opened because "
                f"no branch was available. Please open an account for them separately."
            )
        return redirect("customer_list")

    return render(request, "users/register_customer.html")


@login_required
@user_passes_test(is_admin_or_employee)
def customer_list(request):
    customers = Customer.objects.select_related("user").all()
    return render(request, "users/customer_list.html", {"customers": customers})


@login_required
@user_passes_test(is_admin_or_employee)
def update_customer(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)

    if request.method == "POST":
        customer.customer_type = request.POST["customer_type"]
        customer.dob = request.POST["dob"]
        customer.gender = request.POST["gender"]
        customer.address = request.POST["address"]
        customer.kyc_status = request.POST["kyc_status"]
        customer.save()
        messages.success(request, "Customer updated successfully.")
        return redirect("customer_list")

    return render(request, "users/update_customer.html", {"customer": customer})


@login_required
@user_passes_test(is_admin_or_employee)
def deactivate_customer(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)
    customer.user.is_active = False
    customer.user.save()
    messages.success(request, f"{customer.user.username} has been deactivated.")
    return redirect("customer_list")


@login_required
@user_passes_test(is_admin_or_employee)
def activate_customer(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)
    customer.user.is_active = True
    customer.user.save()
    messages.success(request, f"{customer.user.username} has been reactivated.")
    return redirect("customer_list")