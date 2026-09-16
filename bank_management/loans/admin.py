from django.contrib import admin
from .models import Loan, LoanRepayment, LoanEligibilityRule, LoanDocument

admin.site.register(Loan)
admin.site.register(LoanRepayment)
admin.site.register(LoanEligibilityRule)
admin.site.register(LoanDocument)