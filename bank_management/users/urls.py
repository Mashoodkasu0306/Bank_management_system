from django.urls import path
from . import views

urlpatterns = [
    path("", views.home_redirect, name="home"),
    path("login/", views.user_login, name="login"),
    path("logout/", views.user_logout, name="logout"),
    path("customer/dashboard/", views.customer_dashboard, name="customer_dashboard"),
    path("employee/dashboard/", views.employee_dashboard, name="employee_dashboard"),
    path("dashboard/admin/", views.admin_dashboard, name="admin_dashboard"),
    path("customers/register/", views.register_customer, name="register_customer"),
    path("customers/", views.customer_list, name="customer_list"),
    path("customers/<int:customer_id>/update/", views.update_customer, name="update_customer"),
    path("customers/<int:customer_id>/deactivate/", views.deactivate_customer, name="deactivate_customer"),
    path("customers/<int:customer_id>/activate/", views.activate_customer, name="activate_customer"),
]