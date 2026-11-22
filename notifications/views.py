from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.shortcuts import render
from accounts.models import User

from .models import Notification,PushSubscription
from .services import maybe_sync_overdue, panel_context


import json

from .push import is_allowed_endpoint

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












@login_required
@require_POST
def push_subscribe(request):
    try:
        data = json.loads(request.body)
        endpoint = data['endpoint']
        p256dh = data['keys']['p256dh']
        auth = data['keys']['auth']
    except (ValueError, KeyError, TypeError):
        return JsonResponse({'ok': False}, status=400)
    if not (isinstance(endpoint, str) and isinstance(p256dh, str) and isinstance(auth, str)):
        return JsonResponse({'ok': False}, status=400)
    if not is_allowed_endpoint(endpoint):
        return JsonResponse({'ok': False}, status=400)

    # One browser belongs to one user: the person logged in right now
    PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            'user': request.user,
            'p256dh': p256dh,
            'auth': auth,
            'session_key': request.session.session_key or '',
            'user_agent': request.META.get('HTTP_USER_AGENT', '')[:300],
        },
    )
    return JsonResponse({'ok': True})


@login_required
@require_POST
def push_unsubscribe(request):
    try:
        endpoint = json.loads(request.body)['endpoint']
    except (ValueError, KeyError, TypeError):
        return JsonResponse({'ok': False}, status=400)
    PushSubscription.objects.filter(user=request.user, endpoint=endpoint).delete()
    return JsonResponse({'ok': True})
