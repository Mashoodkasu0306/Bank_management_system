from django.urls import path
from . import views

urlpatterns = [
    path("", views.audit_log_list, name="audit_log"),
    path("alerts/", views.security_alerts, name="security_alerts"),
    path("alerts/<int:alert_id>/review/", views.review_alert, name="review_alert"),
]