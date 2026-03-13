from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from users.models import Customer
from .models import Account

@login_required
def create_account(request):
    # Only employees allowed
    if not hasattr(request.user, 'employee'):
        return redirect("login")

    customers = Customer.objects.all()

    if request.method == "POST":
        customer_id = request.POST.get("customer")
        account_type = request.POST.get("account_type")

        customer = Customer.objects.get(id=customer_id)

        Account.objects.create(
            customer=customer,
            account_type=account_type
        )

        return redirect("employee_dashboard")

    return render(request, "accounts/create_account.html", {"customers": customers})
