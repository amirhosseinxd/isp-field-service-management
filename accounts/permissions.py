
from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def role_required(*roles):
    """Allowing only loggedin users whos roles is in `roles`"""
    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if request.user.role not in roles:
                raise PermissionDenied  #basic 403 page
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator