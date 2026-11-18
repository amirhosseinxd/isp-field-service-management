from accounts.models import User

from .push import public_key_or_empty
from .services import maybe_sync_overdue, panel_context


def notifications(request):
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}
    if user.role == User.Role.ADMIN:
        maybe_sync_overdue()   # support pages keep the "waiting 14+ days" notices up to date
    # An empty key means push isn't set up, and the enable button stays hidden
    return {'notif': panel_context(user), 'vapid_public_key': public_key_or_empty()}