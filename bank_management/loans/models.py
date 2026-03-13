from django.db import models
from users.models import Customer
from bank.models import Branch
from accounts.models import Account

class Loan(models.Model):
    LOAN_TYPES = [
        ("HOME", "Home Loan"),
        ("PERSONAL", "Personal Loan"),
        ("EDUCATION", "Education Loan"),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    loan_type = models.CharField(max_length=20, choices=LOAN_TYPES)
    loan_amount = models.DecimalField(max_digits=12, decimal_places=2)
    interest_rate = models.DecimalField(max_digits=5, decimal_places=2)
    tenure_months = models.IntegerField()
    loan_status = models.CharField(
        max_length=20,
        choices=[("APPROVED", "Approved"), ("REJECTED", "Rejected"), ("ONGOING", "Ongoing")]
    )
    issue_date = models.DateField(auto_now_add=True)
    end_date = models.DateField()

    def __str__(self):
        return f"{self.loan_type} - {self.loan_amount}"