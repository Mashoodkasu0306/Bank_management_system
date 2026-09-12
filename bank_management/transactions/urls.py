from django.urls import path
from . import views

urlpatterns = [
    path("deposit/", views.deposit_view, name="deposit"),
    path("withdraw/", views.withdraw_view, name="withdraw"),
    path("transfer/", views.transfer_view, name="transfer"),
    path("history/<int:account_id>/", views.transaction_history, name="transaction_history"),
    path("all/", views.all_transactions, name="all_transactions"),
    path("my-transfer/", views.customer_transfer_view, name="customer_transfer"),
    path("search/", views.customer_search_transactions, name="customer_search_transactions"),
    path("my/", views.my_transactions, name="my_transactions"),
    path("employee-search/", views.employee_search_customer_transactions, name="employee_search_customer_transactions"),
    path("pending/", views.pending_transactions, name="pending_transactions"),
    path("approve/<int:txn_id>/", views.approve_transaction, name="approve_transaction"),
    path("branch-report/", views.branch_report, name="branch_report"),
]