from django.contrib.auth import get_user_model
from django.utils import timezone

UPDATE_EVERY_SECONDS = 60

# Requests the browser makes by itself, not because a person did something
IGNORED_PREFIXES = (
    '/static/', '/media/', '/sw.js', '/manifest.webmanifest', '/pwa/', '/offline/',
    '/notifications/panel/', '/notifications/push/', '/messages/unread/',
)


class LastSeenMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith(IGNORED_PREFIXES):
            return response
        user = request.user
        if user.is_authenticated:
            now = timezone.now()
            if user.last_seen is None or (now - user.last_seen).total_seconds() >= UPDATE_EVERY_SECONDS:
                # .update() writes one column and skips save() signals; it is the cheap way to do this
                get_user_model().objects.filter(pk=user.pk).update(last_seen=now)
                user.last_seen = now
        return response