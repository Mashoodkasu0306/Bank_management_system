from django.contrib import admin
from .models import Service, ServiceUsage

admin.site.register(Service)
admin.site.register(ServiceUsage)