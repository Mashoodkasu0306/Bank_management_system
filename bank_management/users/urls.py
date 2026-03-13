from django.urls import path
from . import views

urlpatterns = [
    path("login/", views.user_login, name="login"),
    path("logout/", views.user_logout, name="logout"),
    path("customer/dashboard/", views.customer_dashboard, name="customer_dashboard"),
    path("employee/dashboard/", views.employee_dashboard, name="employee_dashboard"),
]