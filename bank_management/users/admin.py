from django.contrib import admin
from .models import Customer, Employee


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("user", "customer_type", "gender", "kyc_status")
    list_filter = ("customer_type", "kyc_status", "gender")
    search_fields = ("user__username",)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("user", "branch", "role", "department", "date_of_joining")
    list_filter = ("branch", "role", "department")
    search_fields = ("user__username",)
