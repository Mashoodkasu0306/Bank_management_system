from django.urls import path
from . import views, card_views, freeze_views

urlpatterns = [
    # ------------------------------------------------------------------
    # KYC VERIFICATION - CUSTOMER
    # ------------------------------------------------------------------
    path("kyc/", views.kyc_dashboard, name="kyc_dashboard"),
    path("kyc/upload/", views.upload_kyc_document, name="upload_kyc_document"),

    # ------------------------------------------------------------------
    # ATM CARD - CUSTOMER
    # ------------------------------------------------------------------
    path("atm-card/request/", views.request_atm_card, name="request_atm_card"),
    path("atm-card/<int:request_id>/status/", views.atm_card_status, name="atm_card_status"),
    path("atm-card/my/", views.my_atm_cards, name="my_atm_cards"),

    # ------------------------------------------------------------------
    # CHEQUE BOOK - CUSTOMER
    # ------------------------------------------------------------------
    path("cheque-book/request/", views.request_cheque_book, name="request_cheque_book"),
    path("cheque-book/<int:request_id>/status/", views.cheque_book_status, name="cheque_book_status"),
    path("cheque-book/my/", views.my_cheque_books, name="my_cheque_books"),
    path("cheque-book/<int:request_id>/pay-fee/", views.pay_cheque_book_fee, name="pay_cheque_book_fee"),
    path("cheque-book/<int:request_id>/pay-fee/confirm/", views.confirm_pay_cheque_book_fee, name="confirm_pay_cheque_book_fee"),

    # ------------------------------------------------------------------
    # ACCOUNT STATEMENT
    # ------------------------------------------------------------------
    path("statement/<int:account_id>/download/", views.download_account_statement, name="download_account_statement"),

    # ------------------------------------------------------------------
    # CARD CONTROLS - CUSTOMER
    # ------------------------------------------------------------------
    path("cards/controls/", card_views.card_controls, name="card_controls"),
    path("cards/<int:card_id>/freeze/", card_views.card_freeze_toggle, name="card_freeze_toggle"),
    path("cards/<int:card_id>/limit/", card_views.card_set_limit, name="card_set_limit"),
    path("cards/emergency-freeze/", card_views.emergency_freeze_start, name="emergency_freeze_start"),

    # ------------------------------------------------------------------
    # STAFF: KYC APPROVAL
    # ------------------------------------------------------------------
    path("staff/kyc/pending/", views.pending_kyc_documents, name="pending_kyc_documents"),
    path("staff/kyc/customer/<int:customer_id>/", views.review_customer_kyc, name="review_customer_kyc"),
    path("staff/kyc/<int:document_id>/verify/", views.verify_kyc_document, name="verify_kyc_document"),

    # ------------------------------------------------------------------
    # STAFF: ATM CARD APPROVAL
    # ------------------------------------------------------------------
    path("staff/atm-card/pending/", views.pending_atm_card_requests, name="pending_atm_card_requests"),
    path("staff/atm-card/<int:request_id>/approve/", views.approve_atm_card_request, name="approve_atm_card_request"),

    # ------------------------------------------------------------------
    # STAFF: CHEQUE BOOK APPROVAL
    # ------------------------------------------------------------------
    path("staff/cheque-book/pending/", views.pending_cheque_book_requests, name="pending_cheque_book_requests"),
    path("staff/cheque-book/<int:request_id>/approve/", views.approve_cheque_book_request, name="approve_cheque_book_request"),

    # ------------------------------------------------------------------
    # STAFF: SERVICES DASHBOARD
    # ------------------------------------------------------------------
    path("staff/dashboard/", views.services_dashboard, name="services_dashboard"),

    # ------------------------------------------------------------------
    # STAFF: EMERGENCY FREEZES
    # ------------------------------------------------------------------
    path("staff/frozen-customers/", freeze_views.frozen_customers, name="frozen_customers"),
    path("staff/frozen-customers/<int:freeze_id>/lift/", freeze_views.lift_freeze, name="lift_freeze"),
]