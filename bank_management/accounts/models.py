from django.db import models
from users.models import Customer
from bank.models import Branch

class Account(models.Model):
    ACCOUNT_TYPES = [
        ("SAVINGS", "Savings"),
        ("CURRENT", "Current"),
        ("LOAN", "Loan"),
    ]

    account_no = models.CharField(max_length=20, unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="accounts")
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    account_type = models.CharField(max_length=10, choices=ACCOUNT_TYPES)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    status = models.CharField(
        max_length=20,
        choices=[("ACTIVE", "Active"), ("CLOSED", "Closed")]
    )
    open_date = models.DateField(auto_now_add=True)

    def __str__(self):
        return self.account_no