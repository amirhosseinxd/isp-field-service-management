from django.db.models.signals import post_save
from django.dispatch import receiver

from jobs.models import Job

from .services import notify_job_assigned, retire_assignment_notices


@receiver(post_save, sender=Job)
def notify_on_assignment(sender, instance, created, raw=False, update_fields=None, **kwargs):
    if raw:
        return
    if created:
        notify_job_assigned(instance)
        return
    # A partial save that doesn't touch the technician can't be a reassignment
    if update_fields is not None and not {'assigned_operator', 'assigned_operator_id'} & set(update_fields):
        return
    previous = getattr(instance, '_loaded_operator_id', None)
    if previous is not None and previous != instance.assigned_operator_id:
        retire_assignment_notices(instance)
        notify_job_assigned(instance)