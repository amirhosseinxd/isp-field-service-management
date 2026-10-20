from django.contrib.auth.models import AbstractUser
from django.db import models

# Create your models here.
class User(AbstractUser):
    class Role(models.TextChoices):
        OPERATOR = 'operator', 'کارشناس میدانی'
        ADMIN = 'admin', 'مدیر پشتیبانی'

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.OPERATOR)
    phone = models.CharField(max_length=30, blank=True)

    @property
    def is_operator(self):
        return self.role == self.Role.OPERATOR

    @property
    def is_support_admin(self):
        return self.role == self.Role.ADMIN

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.role})"