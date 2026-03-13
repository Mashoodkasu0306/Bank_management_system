from django.db import models

class Bank(models.Model):
    name = models.CharField(max_length=100)
    contact_no = models.CharField(max_length=15)
    head_office_address = models.TextField()

    def __str__(self):
        return self.name


class Branch(models.Model):
    bank = models.ForeignKey(Bank, on_delete=models.CASCADE, related_name="branches")
    branch_name = models.CharField(max_length=100)
    ifsc_code = models.CharField(max_length=11, unique=True)
    city = models.CharField(max_length=50)
    status = models.CharField(
        max_length=20,
        choices=[("ACTIVE", "Active"), ("INACTIVE", "Inactive")]
    )

    def __str__(self):
        return f"{self.branch_name} ({self.ifsc_code})"