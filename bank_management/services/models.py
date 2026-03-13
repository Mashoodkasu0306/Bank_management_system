from django.db import models
from users.models import Customer

class Service(models.Model):
    name = models.CharField(max_length=100)
    status = models.CharField(
        max_length=20,
        choices=[("ACTIVE", "Active"), ("INACTIVE", "Inactive")]
    )
    issue_date = models.DateField(auto_now_add=True)

    def __str__(self):
        return self.name


class ServiceUsage(models.Model):
    service = models.ForeignKey(Service, on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    used_at = models.DateTimeField(auto_now_add=True)