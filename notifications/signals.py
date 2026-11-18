from django.contrib.auth.signals import user_logged_out
from django.db.models.signals import post_save
from django.dispatch import receiver

from jobs.models import Job

from .models import PushSubscription
from .services import notify_job_assigned, retire_assignment_notices


@receiver(post_save, sender=Job)
def notify_on_assignment(sender, instance, created, raw=False, update_fields=None, **kwargs):
    if raw:
        return
    if created:
        # A technician continuing their own work shouldn't be told about the job they just made
        if instance.created_by_id != instance.assigned_operator_id:
            notify_job_assigned(instance)
        return
    # A partial save that doesn't touch the technician can't be a reassignment
    if update_fields is not None and not {'assigned_operator', 'assigned_operator_id'} & set(update_fields):
        return
    previous = getattr(instance, '_loaded_operator_id', None)
    if previous is not None and previous != instance.assigned_operator_id:
        retire_assignment_notices(instance)
        notify_job_assigned(instance)


@receiver(user_logged_out)
def drop_this_devices_push_subscription(sender, request, user, **kwargs):
    """Whoever uses this browser next must not receive the previous person's notifications."""
    if user is None or request is None or not request.session.session_key:
        return
    PushSubscription.objects.filter(user=user, session_key=request.session.session_key).delete()