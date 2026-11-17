from django.db.models.signals import post_delete, post_save
from django.utils import timezone

from .models import Job, JobEvidence, JobMaterialUsage, JobReturn, WorkReport


def touch_job(sender, instance, **kwargs):
    """Any change to a job's evidence, materials, report or returns counts as job activity."""
    Job.objects.filter(pk=instance.job_id).update(updated_at=timezone.now())


for model in (JobEvidence, JobMaterialUsage, WorkReport, JobReturn):
    post_save.connect(touch_job, sender=model)
    post_delete.connect(touch_job, sender=model)