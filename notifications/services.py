from datetime import timedelta

from django.core.cache import cache
from django.db import transaction
from django.db.models import Case, IntegerField, Value, When
from django.utils import timezone

from accounts.models import User
from accounts.templatetags.jalali_tags import PERSIAN_DIGITS
from jobs.models import Job

from .models import Notification

OVERDUE_DAYS = 14
RECENT_LIMIT = 15
SYNC_INTERVAL_SECONDS = 600


def notify_job_assigned(job):
    """One notice per (job, technician). Calling this again for the same pair adds nothing."""
    notice, created = Notification.objects.get_or_create(
        dedupe_key=f'assigned:{job.pk}:{job.assigned_operator_id}',
        defaults={
            'recipient_id': job.assigned_operator_id,
            'kind': Notification.Kind.JOB_ASSIGNED,
            'job': job,
        },
    )
    if not created and notice.resolved_at is not None:
        # The job came back to a technician it had been taken away from
        Notification.objects.filter(pk=notice.pk).update(
            created_at=timezone.now(), read_at=None, resolved_at=None,
        )
    return notice


def retire_assignment_notices(job):
    """After a reassignment, the previous technician's notice is no longer relevant."""
    Notification.objects.filter(
        kind=Notification.Kind.JOB_ASSIGNED, job=job, resolved_at__isnull=True,
    ).exclude(recipient_id=job.assigned_operator_id).update(resolved_at=timezone.now())


def overdue_jobs(now):
    """Jobs whose customer registered at least OVERDUE_DAYS ago and that are not yet reviewed."""
    cutoff = now - timedelta(days=OVERDUE_DAYS)
    return Job.objects.filter(customer__registered_at__lte=cutoff).exclude(
        status=Job.Status.REVIEWED,
    )


@transaction.atomic
def sync_overdue_notifications(now=None):
    """Create missing notices for support staff and retire the ones that no longer apply."""
    now = now or timezone.now()
    overdue = overdue_jobs(now)
    admins = list(User.objects.filter(role=User.Role.ADMIN, is_active=True))

    candidates = []
    for job in overdue.select_related('customer'):
        # When the situation began: 14 days after registration, or when the job was created if later
        since = max(job.customer.registered_at + timedelta(days=OVERDUE_DAYS), job.created_at)
        for admin in admins:
            candidates.append(Notification(
                recipient=admin, kind=Notification.Kind.JOB_OVERDUE, job=job,
                dedupe_key=f'overdue:{job.pk}:{admin.pk}', created_at=since,
            ))
    # Rows whose dedupe_key already exists are skipped, so repeated runs create nothing new
    Notification.objects.bulk_create(candidates, batch_size=500, ignore_conflicts=True)

    kind = Notification.Kind.JOB_OVERDUE
    # The situation exists again (for example a date was corrected): bring the notice back
    Notification.objects.filter(kind=kind, resolved_at__isnull=False, job__in=overdue).update(
        resolved_at=None,
    )
    # The situation is gone (the job was reviewed): retire the notice, keeping its read state
    Notification.objects.filter(kind=kind, resolved_at__isnull=True).exclude(
        job__in=overdue,
    ).update(resolved_at=now)
    return overdue.count()


def maybe_sync_overdue():
    """Run the check from page visits, but at most once every few minutes."""
    if cache.add('notifications:overdue-sync', True, SYNC_INTERVAL_SECONDS):
        sync_overdue_notifications()


def unread_count(user):
    return Notification.objects.filter(
        recipient=user, read_at__isnull=True, resolved_at__isnull=True,
    ).count()


def panel_context(user):
    """What the bell needs: the latest notices (unread ones first), the count and the badge text."""
    items = list(
        Notification.objects.filter(recipient=user)
        .select_related('job__customer')
        .annotate(sort_group=Case(
            When(read_at__isnull=True, resolved_at__isnull=True, then=Value(0)),
            default=Value(1), output_field=IntegerField(),
        ))
        .order_by('sort_group', '-created_at', '-id')[:RECENT_LIMIT]
    )
    unread = unread_count(user)
    badge = ('۹+' if unread > 9 else str(unread)).translate(PERSIAN_DIGITS)
    return {'items': items, 'unread': unread, 'badge': badge}