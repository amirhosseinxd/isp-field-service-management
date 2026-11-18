from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


class Notification(models.Model):
    class Kind(models.TextChoices):
        JOB_ASSIGNED = 'job_assigned', 'ارجاع کار'
        JOB_OVERDUE = 'job_overdue', 'کار معوق'

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications',
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    job = models.ForeignKey('jobs.Job', on_delete=models.CASCADE, related_name='notifications')
    dedupe_key = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(default=timezone.now)
    read_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['recipient', 'read_at'])]

    def __str__(self):
        return f'{self.get_kind_display()} → {self.recipient} (کار {self.job_id})'

    def target_url(self):
        if self.kind == self.Kind.JOB_ASSIGNED:
            return reverse('job_start', args=[self.job_id])        # the technician opens the job
        return reverse('support_job_detail', args=[self.job_id])   # support opens the job's details







class PushSubscription(models.Model):
    """One browser on one device that has agreed to receive pushes for one user."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='push_subscriptions',
    )
    endpoint = models.TextField(unique=True)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    session_key = models.CharField(max_length=64, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.user} — {self.endpoint[:40]}'