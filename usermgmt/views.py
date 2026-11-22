from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST

from django.utils import timezone

from notifications.models import Notification

from .rules import can_edit_profile, can_manage, creatable_roles, unfinished_jobs

from accounts.models import User, online_cutoff
from accounts.permissions import role_required
from audit.models import AuditEntry
from audit.services import log
from jobs.models import Job
from jobs.views import paginate

from .forms import AdminSetPasswordForm, UserCreateForm, UserEditForm, UserFilterForm



@role_required(User.Role.ADMIN)
def user_list(request):
    form = UserFilterForm(request.GET or None)
    users = User.objects.all()
    if form.is_valid():
        cd = form.cleaned_data
        for term in cd['q'].split():      # every word must match something
            users = users.filter(
                Q(username__icontains=term) | Q(first_name__icontains=term)
                | Q(last_name__icontains=term) | Q(phone__icontains=term)
            )
        if cd['role']:
            users = users.filter(role=cd['role'])
        if cd['status'] == 'active':
            users = users.filter(is_active=True)
        elif cd['status'] == 'inactive':
            users = users.filter(is_active=False)
    users = users.order_by('-is_active', 'username')

    page, qs = paginate(request, users, 20)
    rows = [
        {'user': u, 'can_edit': can_edit_profile(request.user, u)}
        for u in page
    ]
    online_count = User.objects.filter(
        role=User.Role.OPERATOR, is_active=True, last_seen__gte=online_cutoff(),
    ).count()
    return render(request, 'usermgmt/user_list.html', {
        'form': form, 'page': page, 'qs': qs, 'rows': rows, 'online_count': online_count,
        'can_create_support': User.Role.ADMIN in creatable_roles(request.user),
    })


@role_required(User.Role.ADMIN)
@sensitive_post_parameters('password1', 'password2')
def user_create(request):
    allowed = creatable_roles(request.user)
    initial = {}
    if request.GET.get('role') in allowed:
        initial['role'] = request.GET['role']
    form = UserCreateForm(request.POST or None, actor=request.user, initial=initial)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            user = form.save()
            details = f'نقش: {user.get_role_display()} | نام کاربری: {user.username}'
            if user.can_manage_accounts:
                details += ' | دسترسی مدیریت حساب‌ها'
            log(request.user, AuditEntry.Action.USER_CREATED, user, details=details, request=request)
        messages.success(request, f'حساب «{user.display_name}» ساخته شد.')
        return redirect('user_list')
    return render(request, 'usermgmt/user_form.html', {'form': form, 'creating': True})


@role_required(User.Role.ADMIN)
def user_edit(request, pk):
    target = get_object_or_404(User, pk=pk)
    if not can_edit_profile(request.user, target):
        raise PermissionDenied
    # Read these BEFORE the form is built: validating a ModelForm changes the object in memory
    subject_name = target.display_name
    before_role, before_flag = target.role, target.can_manage_accounts
    is_self = target.pk == request.user.pk

    form = UserEditForm(request.POST or None, instance=target, actor=request.user)
    if request.method == 'POST' and form.is_valid():
        profile_fields = ('username', 'first_name', 'last_name', 'phone')
        changed = [str(form.fields[n].label) for n in form.changed_data if n in profile_fields]
        with transaction.atomic():
            form.save()
            role_changed = target.role != before_role
            flag_changed = target.can_manage_accounts != before_flag
            if changed:
                log(
                    request.user, AuditEntry.Action.USER_UPDATED, target, request=request,
                    details=f'نام کاربری: {target.username} | تغییر: ' + '، '.join(changed),
                )
            if role_changed:
                log(
                    request.user, AuditEntry.Action.USER_ROLE_CHANGED, target, request=request,
                    details=(f'نام کاربری: {target.username} | '
                             f'از «{User.Role(before_role).label}» به «{target.get_role_display()}»'),
                )
                # Notices of the old role would point to pages this person can no longer open
                Notification.objects.filter(recipient=target, resolved_at__isnull=True).update(
                    resolved_at=timezone.now(),
                )
            if flag_changed:
                log(
                    request.user, AuditEntry.Action.USER_ACCESS_CHANGED, target, request=request,
                    details=(f'نام کاربری: {target.username} | مدیریت حساب‌ها: '
                             + ('داده شد' if target.can_manage_accounts else 'برداشته شد')),
                )
        if changed or role_changed or flag_changed:
            messages.success(request, 'تغییرات ذخیره شد.')
        else:
            messages.info(request, 'تغییری انجام نشد.')
        return redirect('user_list')

    target.refresh_from_db()     # after a failed POST the object may hold values that were not saved
    return render(request, 'usermgmt/user_form.html', {
        'form': form, 'creating': False, 'target': target, 'subject_name': subject_name,
        'is_self': is_self, 'can_manage': can_manage(request.user, target),
        'open_jobs': unfinished_jobs(target).count() if target.role == User.Role.OPERATOR else 0,
    })

@role_required(User.Role.ADMIN)
@require_POST
def user_set_active(request, pk):
    target = get_object_or_404(User, pk=pk)
    if not can_manage(request.user, target):
        raise PermissionDenied
    action = request.POST.get('action')
    if action not in ('activate', 'deactivate'):
        return HttpResponseBadRequest()
    activate = action == 'activate'

    if target.is_active == activate:          # e.g. a double click or two admins at once
        messages.info(request, 'وضعیت این حساب از قبل همین بود.')
    else:
        with transaction.atomic():
            target.is_active = activate
            target.save(update_fields=['is_active'])
            log(
                request.user,
                AuditEntry.Action.USER_ACTIVATED if activate else AuditEntry.Action.USER_DEACTIVATED,
                target, request=request, details=f'نام کاربری: {target.username}',
            )
        messages.success(request, 'حساب فعال شد.' if activate else 'حساب غیرفعال شد.')
    return redirect('user_list')


@role_required(User.Role.ADMIN)
@sensitive_post_parameters('new_password1', 'new_password2')
def user_set_password(request, pk):
    target = get_object_or_404(User, pk=pk)
    if not can_edit_profile(request.user, target):
        raise PermissionDenied
    is_self = target.pk == request.user.pk

    form = AdminSetPasswordForm(target, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            form.save()
            log(
                request.user, AuditEntry.Action.USER_PASSWORD_RESET, target, request=request,
                details=f'نام کاربری: {target.username}' + (' | توسط خود کاربر' if is_self else ''),
            )
        if is_self:
            update_session_auth_hash(request, target)   # keeps you logged in on this device
        messages.success(request, 'رمز عبور تغییر کرد.')
        return redirect('user_list')
    return render(request, 'usermgmt/user_set_password.html', {
        'form': form, 'subject_name': target.display_name, 'is_self': is_self,
    })