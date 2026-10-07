from django.contrib import admin

from .models import SupportCase, SupportMessage


@admin.register(SupportCase)
class SupportCaseAdmin(admin.ModelAdmin):
    list_display = ("id", "case_type", "customer", "status", "created_at", "due_at")
    list_filter = ("case_type", "status")


@admin.register(SupportMessage)
class SupportMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "case", "from_staff", "created_at")