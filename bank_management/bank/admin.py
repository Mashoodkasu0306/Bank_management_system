from django.contrib import admin
from .models import Bank, Branch


@admin.register(Bank)
class BankAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "established_date", "contact_phone")
    search_fields = ("name", "code")


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "branch_code", "bank", "city", "ifsc_code")
    list_filter = ("bank", "state")
    search_fields = ("name", "branch_code", "ifsc_code")