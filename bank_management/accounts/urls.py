from django.urls import path
from . import views

urlpatterns = [
    path("create/", views.create_account, name="create_account"),
    path("", views.account_list, name="account_list"),
    path("<int:account_id>/", views.account_detail, name="account_detail"),
]