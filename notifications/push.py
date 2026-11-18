import base64
import json
import logging
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization
from django.conf import settings
from django.db import transaction
from django.urls import reverse
from pywebpush import WebPushException, webpush

from accounts.models import User
from accounts.templatetags.jalali_tags import PERSIAN_DIGITS, jalali

from .models import Notification, PushSubscription

logger = logging.getLogger(__name__)

# Browsers only hand out push addresses on these services. Any other address is refused,
# so nobody can make the server send requests to an arbitrary web address.
ALLOWED_PUSH_HOSTS = (
    'fcm.googleapis.com', 'googleapis.com', 'push.services.mozilla.com',
    'push.apple.com', 'notify.windows.com',
)
PUSH_TTL_SECONDS = 6 * 3600     # how long a push service keeps a message for an offline device
PUSH_TIMEOUT_SECONDS = 3


def is_allowed_endpoint(endpoint):
    parsed = urlparse(endpoint)
    host = parsed.hostname or ''
    return parsed.scheme == 'https' and any(
        host == allowed or host.endswith('.' + allowed) for allowed in ALLOWED_PUSH_HOSTS
    )


def vapid_key_path():
    path = getattr(settings, 'VAPID_PRIVATE_KEY_FILE', None)
    return Path(path) if path else None


def vapid_ready():
    path = vapid_key_path()
    return bool(path and path.is_file())


@lru_cache(maxsize=8)
def _derive_public_key(path_str):
    """The public half of the key, in the text format browsers expect."""
    key = serialization.load_pem_private_key(Path(path_str).read_bytes(), password=None)
    raw = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
    )
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def public_key_or_empty():
    if not vapid_ready():
        return ''
    try:
        return _derive_public_key(str(vapid_key_path()))
    except Exception:
        logger.exception('Could not read the VAPID key file')
        return ''


def send_to_user(user, payload):
    """Send one push message to every device of the user. Returns how many devices accepted it."""
    if not vapid_ready() or not user.is_active:
        return 0
    body = json.dumps(payload, ensure_ascii=False)
    delivered = 0
    for subscription in PushSubscription.objects.filter(user=user):
        try:
            webpush(
                subscription_info={
                    'endpoint': subscription.endpoint,
                    'keys': {'p256dh': subscription.p256dh, 'auth': subscription.auth},
                },
                data=body,
                vapid_private_key=str(vapid_key_path()),
                vapid_claims={'sub': getattr(settings, 'VAPID_ADMIN_SUBJECT', 'mailto:admin@example.com')},
                ttl=PUSH_TTL_SECONDS,
                timeout=PUSH_TIMEOUT_SECONDS,
            )
            delivered += 1
        except WebPushException as exc:
            status = getattr(exc.response, 'status_code', None)
            if status in (404, 410):
                subscription.delete()   # the browser unsubscribed, or the subscription expired
            else:
                logger.warning('Push to subscription %s failed: %s', subscription.pk, exc)
        except Exception:
            logger.exception('Push to subscription %s failed', subscription.pk)
    return delivered


def payload_for(notification):
    """The text of the push, matching what the bell shows for the same notification."""
    job = notification.job
    customer = job.customer.full_name if job.customer else 'بدون مشترک'
    if notification.kind == Notification.Kind.JOB_ASSIGNED:
        title = 'کار جدید به شما ارجاع شد'
        body = f'{job.get_workflow_display()} — {customer}'
    else:
        registered = jalali(job.customer.registered_at, '%Y/%m/%d') if job.customer else ''
        title = f'کار معوق: {customer}'
        body = (
            f'ثبت‌نام {registered} · کار {job.pk} · {job.get_workflow_display()} '
            f'· وضعیت: {job.get_status_display()}'
        )
    return {
        'title': title,
        'body': body,
        # Opening this address marks the notice as read, then goes to the job
        'url': reverse('notification_open', args=[notification.pk]),
        'tag': f'notice-{notification.pk}',
    }


def push_notification(notification):
    return send_to_user(notification.recipient, payload_for(notification))


def push_after_commit(notification_pk):
    """Send the push only once the database change that created the notice is saved for good."""
    def send():
        notice = (
            Notification.objects.select_related('recipient', 'job__customer')
            .filter(pk=notification_pk, resolved_at__isnull=True).first()
        )
        if notice is not None:
            push_notification(notice)
    transaction.on_commit(send)


def push_new_overdue(keys_by_recipient):
    """One push per support user: the details for a single new notice, a summary for several."""
    for recipient_id, keys in keys_by_recipient.items():
        user = User.objects.filter(pk=recipient_id, is_active=True).first()
        if user is None or not user.push_subscriptions.exists():
            continue
        if len(keys) == 1:
            notice = (
                Notification.objects.select_related('recipient', 'job__customer')
                .filter(dedupe_key=keys[0]).first()
            )
            if notice is not None:
                push_notification(notice)
        else:
            count = str(len(keys)).translate(PERSIAN_DIGITS)
            send_to_user(user, {
                'title': 'کارهای معوق جدید',
                'body': f'{count} کار نیاز به پیگیری دارد',
                'url': reverse('support_dashboard'),
                'tag': 'overdue-summary',
            })