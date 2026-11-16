from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver

from .models import AuditEntry
from .services import log


@receiver(user_logged_in)
def record_login(sender, request, user, **kwargs):
    log(user, AuditEntry.Action.LOGIN, request=request)


@receiver(user_login_failed)
def record_failed_login(sender, credentials, request=None, **kwargs):
    # Only the username is stored. The password is never recorded.
    log(
        None, AuditEntry.Action.LOGIN_FAILED, request=request,
        username=str(credentials.get('username', ''))[:150],
    )