from accounts.models import User

from .services import maybe_sync_overdue, panel_context


def notifications(request):
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}
    if user.role == User.Role.ADMIN:
        maybe_sync_overdue()   # support pages keep the "waiting 14+ days" notices up to date
    return {'notif': panel_context(user)}