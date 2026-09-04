from django.urls import path
from . import views

urlpatterns = [
    path("deposit/", views.deposit_view, name="deposit"),
    path("withdraw/", views.withdraw_view, name="withdraw"),
    path("transfer/", views.transfer_view, name="transfer"),
    path("history/<int:account_id>/", views.transaction_history, name="transaction_history"),
    path("all/", views.all_transactions, name="all_transactions"),
]