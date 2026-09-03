from django.db import models
from users.models import Customer
from bank.models import Branch


class Account(models.Model):
    ACCOUNT_TYPES = [
        ("SAVINGS", "Savings"),
        ("CURRENT", "Current"),
        ("LOAN", "Loan"),
    ]

    STATUS_CHOICES = [
        ("ACTIVE", "Active"),
        ("CLOSED", "Closed"),
    ]

    account_no = models.CharField(max_length=30, unique=True, editable=False, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="accounts")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="accounts")
    account_type = models.CharField(max_length=10, choices=ACCOUNT_TYPES)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="ACTIVE")
    open_date = models.DateField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.account_no:
            self.account_no = self._generate_account_no()
        super().save(*args, **kwargs)

    def _generate_account_no(self):
        bank_code = self.branch.bank.code
        branch_code = self.branch.branch_code
        prefix = f"{bank_code}-{branch_code}-"

        last_account = Account.objects.filter(
            branch=self.branch,
            account_no__startswith=prefix
        ).order_by("-id").first()

        if last_account:
            last_seq = int(last_account.account_no.split("-")[-1])
            next_seq = last_seq + 1
        else:
            next_seq = 1

        candidate = f"{prefix}{next_seq:06d}"
        while Account.objects.filter(account_no=candidate).exists():
            next_seq += 1
            candidate = f"{prefix}{next_seq:06d}"
        return candidate

    def __str__(self):
        return self.account_no