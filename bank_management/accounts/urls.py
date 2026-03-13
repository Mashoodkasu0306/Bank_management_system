from django.urls import path
from .views import create_account

urlpatterns = [
    path("create-account/", create_account, name="create_account"),
]