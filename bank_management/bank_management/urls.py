from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('users.urls')),
    path("accounts/", include("accounts.urls")),
    path("bank/", include("bank.urls")),
    path("transactions/", include("transactions.urls")),
    path("loans/", include("loans.urls")),
    path("services/", include("services.urls")),
    path("notifications/", include("notifications.urls")),

]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)