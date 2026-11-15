from django.core.validators import RegexValidator
from django.db import models

subscription_id_validator = RegexValidator(
    regex=r'^\d{10}$',
    message='شناسه اشتراک باید دقیقاً ۱۰ رقم باشد.',
)
center_number_validator = RegexValidator(
    regex=r'^\d{2}$',
    message='شماره مرکز باید دقیقاً ۲ رقم باشد.',
)


class City(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'cities'

    def __str__(self):
        return self.name


class Customer(models.Model):
    subscription_id = models.CharField(
        max_length=10, unique=True, validators=[subscription_id_validator],
    )
    full_name = models.CharField(max_length=200)
    mobile = models.CharField(max_length=20)
    address = models.TextField()
    city = models.ForeignKey(City, on_delete=models.PROTECT, related_name='customers')
    center_number = models.CharField(max_length=2, validators=[center_number_validator])
    registered_at = models.DateTimeField()

    # Shown only until this customer has a job of their own (see current_status_display)
    status_label = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ['-registered_at']

    def __str__(self):
        return f"{self.full_name} ({self.subscription_id})"

    @property
    def center(self):
        """The full center code, e.g. 'گرمسار-OAC.03', built from the city and the number."""
        return f"{self.city.name}-OAC.{self.center_number}"

    def current_status_display(self):
        """The status/workflow of this customer's most recent job, or a fallback."""
        latest = self.jobs.order_by('-created_at').first()
        if latest is not None:
            return f"{latest.get_status_display()} — {latest.get_workflow_display()}"
        return self.status_label or 'بدون کار ثبت‌شده'