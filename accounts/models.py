from django.contrib.auth.models import AbstractUser
from django.db import models

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

def online_cutoff():
    """Anyone seen after this moment counts as online."""
    return timezone.now() - timedelta(minutes=getattr(settings, 'USER_ONLINE_MINUTES', 5))


# Create your models here.
class User(AbstractUser):
    class Role(models.TextChoices):
        OPERATOR = 'operator', 'تکنسین'
        ADMIN = 'admin', 'پشتیبان'

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.OPERATOR)
    phone = models.CharField(max_length=30, blank=True)
    # Written by LastSeenMiddleware, at most once a minute per person
    last_seen = models.DateTimeField(null=True, blank=True)
    # Lets a support account create and manage other support accounts. Only the owner can change it.
    can_manage_accounts = models.BooleanField(default=False)

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    @property
    def is_online(self):
        return self.last_seen is not None and self.last_seen >= online_cutoff()

    def __str__(self):
        return f"{self.display_name} ({self.get_role_display()})"

    @property
    def is_operator(self):
        return self.role == self.Role.OPERATOR

    @property
    def is_support_admin(self):
        return self.role == self.Role.ADMIN

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.role})"