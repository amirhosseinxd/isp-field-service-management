from accounts.models import User

from .services import badge_text, unread_count


def inbox(request):
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated or user.role not in (User.Role.OPERATOR, User.Role.ADMIN):
        return {}
    count = unread_count(user)
    return {'inbox_unread': count, 'inbox_badge': badge_text(count)}