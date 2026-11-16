from .models import AuditEntry


def log(actor, action, target=None, details='', request=None, username=''):
    """Write one audit entry. `target` is a model instance (a Job, a Customer) or None."""
    is_user = getattr(actor, 'is_authenticated', False)
    entry = AuditEntry(
        actor=actor if is_user else None,
        actor_username=actor.get_username() if is_user else username,
        action=action,
        details=details,
        ip_address=(request.META.get('REMOTE_ADDR') or None) if request else None,
    )
    if target is not None:
        entry.target_type = target._meta.model_name
        entry.target_id = target.pk
        entry.target_label = str(target)[:200]
    entry.save()
    return entry