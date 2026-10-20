from django.urls import path
from . import views, document_views

urlpatterns = [
    path("apply/", views.apply_loan, name="apply_loan"),
    path("my/", views.my_loans, name="my_loans"),
    path("<int:loan_id>/", views.loan_detail, name="loan_detail"),
    path("<int:loan_id>/upload-document/", views.upload_loan_document, name="upload_loan_document"),
    path("document/<int:document_id>/file/", document_views.loan_document_download, name="loan_document_download"),
    path("pending/", views.pending_loans, name="pending_loans"),
    path("all/", views.all_loans, name="all_loans"),
    path("defaulted/", views.defaulted_loans, name="defaulted_loans"),
    path("<int:loan_id>/approve/", views.approve_loan, name="approve_loan"),
    path("repayment/<int:repayment_id>/pay/", views.pay_emi, name="pay_emi"),
    path("<int:loan_id>/pay-lump-sum/", views.pay_lump_sum, name="pay_lump_sum"),
    path("<int:loan_id>/pay-lump-sum/confirm/", views.confirm_pay_lump_sum, name="confirm_pay_lump_sum"),
    path("<int:loan_id>/foreclose/", views.request_foreclosure, name="request_foreclosure"),
    path("foreclosures/pending/", views.pending_foreclosures, name="pending_foreclosures"),
    path("foreclosures/<int:loan_id>/process/", views.process_foreclosure, name="process_foreclosure"),
    path("<int:loan_id>/renew/", views.renew_loan, name="renew_loan"),
]