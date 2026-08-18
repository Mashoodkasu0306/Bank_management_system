from django.db import models


class Bank(models.Model):
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=20, unique=True)
    established_date = models.DateField(null=True, blank=True)
    head_office_address = models.TextField(blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=15, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Branch(models.Model):
    bank = models.ForeignKey(Bank, on_delete=models.CASCADE, related_name="branches")
    name = models.CharField(max_length=150)
    branch_code = models.CharField(max_length=20, unique=True)
    address = models.TextField()
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    ifsc_code = models.CharField(max_length=15, unique=True)
    contact_phone = models.CharField(max_length=15, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("bank", "branch_code")

    def __str__(self):
        return f"{self.name} ({self.branch_code})"