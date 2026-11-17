from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User

from .models import Notification
from .services import maybe_sync_overdue, panel_context


def _payload(user):
    ctx = panel_context(user)
    return JsonResponse({
        'unread': ctx['unread'],
        'badge': ctx['badge'],
        'html': render_to_string('notifications/_items.html', {'notif': ctx}),
    })


@login_required
def panel(request):
    if request.user.role == User.Role.ADMIN:
        maybe_sync_overdue()
    return _payload(request.user)


@login_required
@require_POST
def mark_read(request, pk):
    Notification.objects.filter(
        pk=pk, recipient=request.user, read_at__isnull=True,
    ).update(read_at=timezone.now())
    return _payload(request.user)


@login_required
@require_POST
def mark_all_read(request):
    Notification.objects.filter(
        recipient=request.user, read_at__isnull=True,
    ).update(read_at=timezone.now())
    return _payload(request.user)


@login_required
def open_notification(request, pk):
    notice = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if notice.read_at is None:
        Notification.objects.filter(pk=notice.pk).update(read_at=timezone.now())
    return redirect(notice.target_url())