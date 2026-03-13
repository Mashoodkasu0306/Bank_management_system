from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from .models import Customer, Employee

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
                return redirect("admin:index")

    return render(request, "users/login.html")


def user_logout(request):
    logout(request)
    return redirect("login")

@login_required
def customer_dashboard(request):
    if not hasattr(request.user, 'customer'):
        return redirect("login")

    return render(request, "users/customer_dashboard.html")


@login_required
def employee_dashboard(request):
    if not hasattr(request.user, 'employee'):
        return redirect("login")

    return render(request, "users/employee_dashboard.html")



