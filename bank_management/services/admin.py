from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Service, ServiceUsage,
    KYCVerification, KYCDocument, ATMCardRequest, ChequebookRequest, AccountStatement
)


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "issue_date")
    list_filter = ("status",)


@admin.register(ServiceUsage)
class ServiceUsageAdmin(admin.ModelAdmin):
    list_display = ("service", "customer", "used_at")


class KYCDocumentInline(admin.TabularInline):
    model = KYCDocument
    extra = 0
    readonly_fields = ("uploaded_at",)


@admin.register(KYCVerification)
class KYCVerificationAdmin(admin.ModelAdmin):
    list_display = ("customer", "status", "created_at", "verified_at", "verified_by")
    list_filter = ("status",)
    search_fields = ("customer__user__username",)
    inlines = [KYCDocumentInline]


@admin.register(KYCDocument)
class KYCDocumentAdmin(admin.ModelAdmin):
    list_display = ("kyc_verification", "document_type", "verification_status", "uploaded_at", "file_preview")
    list_filter = ("document_type", "verification_status")
    search_fields = ("kyc_verification__customer__user__username",)

    def file_preview(self, obj):
        if obj.file:
            return format_html('<a href="{}" target="_blank">View Document</a>', obj.file.url)
        return 'No file'
    file_preview.short_description = 'Document'


@admin.register(ATMCardRequest)
class ATMCardRequestAdmin(admin.ModelAdmin):
    list_display = ("account", "status", "requested_at", "approved_by")
    list_filter = ("status",)
    search_fields = ("account__account_no",)


@admin.register(ChequebookRequest)
class ChequebookRequestAdmin(admin.ModelAdmin):
    list_display = ("account", "leaf_count", "status", "cheque_book_fee", "fee_charged", "requested_at")
    list_filter = ("status", "leaf_count", "fee_charged")
    search_fields = ("account__account_no",)


@admin.register(AccountStatement)
class AccountStatementAdmin(admin.ModelAdmin):
    list_display = ("account", "start_date", "end_date", "generated_at", "requested_by")
    search_fields = ("account__account_no",)