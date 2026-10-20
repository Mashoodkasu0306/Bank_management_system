from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('', include('core.pwa_urls')),
    path('admin/', admin.site.urls),
    path('', include('users.urls')),
    path("accounts/", include("accounts.urls")),
    path("bank/", include("bank.urls")),
    path("transactions/", include("transactions.urls")),
    path("loans/", include("loans.urls")),
    path("services/", include("services.urls")),
    path("notifications/", include("notifications.urls")),
    path("audit/", include("audit.urls")),
    path("reports/", include("reports.urls")),
    path("support/", include("support.urls")),
    path("planning/", include("planning.urls")),

]

