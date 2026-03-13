from django.contrib import admin

# Register your models here.

from .models import Bank, Branch

admin.site.register(Bank)
admin.site.register(Branch)