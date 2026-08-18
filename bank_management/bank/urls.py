from django.urls import path
from . import views

urlpatterns = [
    path("banks/", views.bank_list, name="bank_list"),
    path("banks/create/", views.create_bank, name="create_bank"),
    path("branches/", views.branch_list, name="branch_list"),
    path("branches/create/", views.create_branch, name="create_branch"),
    path("employees/assign/", views.assign_employee, name="assign_employee"),
]