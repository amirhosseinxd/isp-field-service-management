from accounts.models import User
from jobs.models import Job


def _is_support(user):
    return user.is_authenticated and user.is_active and user.role == User.Role.ADMIN


def is_owner(user):
    """The owner is the Django superuser."""
    return _is_support(user) and user.is_superuser


def is_account_manager(user):
    return _is_support(user) and (user.is_superuser or user.can_manage_accounts)


def can_manage(actor, target):
    """May `actor` edit, (de)activate or reset the password of `target`? Never for yourself."""
    if not _is_support(actor) or actor.pk == target.pk:
        return False
    if actor.is_superuser:
        return True
    # From here on the actor is not the owner
    if target.is_superuser or target.is_staff or target.can_manage_accounts:
        return False                       # the owner and account managers: owner only
    if target.role == User.Role.ADMIN:
        return actor.can_manage_accounts   # ordinary support accounts: managers only
    return True                            # technicians: any support account


def can_edit_profile(actor, target):
    """Your own name/phone, or anyone you may manage. Also decides who may set a password."""
    return _is_support(actor) and (actor.pk == target.pk or can_manage(actor, target))


def creatable_roles(actor):
    if not _is_support(actor):
        return []
    roles = [User.Role.OPERATOR]
    if is_account_manager(actor):
        roles.append(User.Role.ADMIN)
    return roles


def unfinished_jobs(user):
    return Job.objects.filter(assigned_operator=user).exclude(
        status__in=[Job.Status.SUBMITTED, Job.Status.REVIEWED],
    )