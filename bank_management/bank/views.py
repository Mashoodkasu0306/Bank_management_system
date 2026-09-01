from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Bank, Branch
from users.models import Employee, Customer


def is_admin(user):
    if not user.is_authenticated:
        return False
    if Customer.objects.filter(user=user).exists():
        return False
    if Employee.objects.filter(user=user).exists():
        return False
    return True


def is_admin_or_employee(user):
    if not user.is_authenticated:
        return False
    if Customer.objects.filter(user=user).exists():
        return False
    return True  # admin (no records) OR employee — both allowed to view


@login_required
@user_passes_test(is_admin_or_employee)
def bank_list(request):
    banks = Bank.objects.all()
    return render(request, "bank/bank_list.html", {"banks": banks})


@login_required
@user_passes_test(is_admin)
def create_bank(request):
    if request.method == "POST":
        Bank.objects.create(
            name=request.POST["name"],
            code=request.POST["code"],
            head_office_address=request.POST.get("head_office_address", ""),
            contact_email=request.POST.get("contact_email", ""),
            contact_phone=request.POST.get("contact_phone", ""),
        )
        messages.success(request, "Bank created successfully.")
        return redirect("bank_list")
    return render(request, "bank/create_bank.html")


@login_required
@user_passes_test(is_admin_or_employee)
def branch_list(request):
    branches = Branch.objects.select_related("bank").all()
    return render(request, "bank/branch_list.html", {"branches": branches})


@login_required
@user_passes_test(is_admin)
def create_branch(request):
    banks = Bank.objects.all()
    if request.method == "POST":
        bank = get_object_or_404(Bank, id=request.POST["bank"])
        Branch.objects.create(
            bank=bank,
            name=request.POST["name"],
            branch_code=request.POST["branch_code"],
            address=request.POST["address"],
            city=request.POST["city"],
            state=request.POST["state"],
            ifsc_code=request.POST["ifsc_code"],
            contact_phone=request.POST.get("contact_phone", ""),
        )
        messages.success(request, "Branch created successfully.")
        return redirect("branch_list")
    return render(request, "bank/create_branch.html", {"banks": banks})


@login_required
@user_passes_test(is_admin)
def assign_employee(request):
    branches = Branch.objects.all()
    employees = Employee.objects.filter(branch__isnull=True)
    if request.method == "POST":
        employee = get_object_or_404(Employee, id=request.POST["employee"])
        branch = get_object_or_404(Branch, id=request.POST["branch"])
        employee.branch = branch
        employee.save()
        messages.success(request, f"{employee.user.username} assigned to {branch.name}.")
        return redirect("assign_employee")
    return render(request, "bank/assign_employee.html", {"branches": branches, "employees": employees})