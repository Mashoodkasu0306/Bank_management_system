from django.db import models
from django.contrib.auth.models import User
from bank.models import Branch

class Customer(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    customer_type = models.CharField(
        max_length=20,
        choices=[("INDIVIDUAL", "Individual"), ("BUSINESS", "Business")]
    )
    dob = models.DateField()
    gender = models.CharField(
        max_length=10,
        choices=[("MALE", "Male"), ("FEMALE", "Female"), ("OTHER", "Other")]
    )
    address = models.TextField()
    kyc_status = models.CharField(
        max_length=20,
        choices=[("PENDING", "Pending"), ("VERIFIED", "Verified")]
    )

    def __str__(self):
        return self.user.username


class Employee(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True)
    role = models.CharField(max_length=50)
    department = models.CharField(max_length=50)
    salary = models.DecimalField(max_digits=10, decimal_places=2)
    date_of_joining = models.DateField()

    def __str__(self):
        return self.user.username
