from django.urls import path
from . import views

urlpatterns = [
    path("", views.notifications_list, name="notifications_list"),
    path("<int:notification_id>/read/", views.mark_notification_read, name="mark_notification_read"),
    path("mark-all-read/", views.mark_all_read, name="mark_all_read"),
]