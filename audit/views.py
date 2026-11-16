from django.db.models import Q
from django.shortcuts import render

from accounts.models import User
from accounts.permissions import role_required
from jobs.views import paginate

from .forms import AuditFilterForm
from .models import AuditEntry


@role_required(User.Role.ADMIN)
def audit_list(request):
    form = AuditFilterForm(request.GET or None)
    entries = AuditEntry.objects.all()
    if form.is_valid():
        cd = form.cleaned_data
        if cd['action']:
            entries = entries.filter(action=cd['action'])
        if cd['q']:
            q = cd['q']
            entries = entries.filter(
                Q(actor_username__icontains=q)
                | Q(target_label__icontains=q)
                | Q(details__icontains=q)
            )
        if cd['date_from']:
            entries = entries.filter(created_at__date__gte=cd['date_from'])
        if cd['date_to']:
            entries = entries.filter(created_at__date__lte=cd['date_to'])

    page, qs = paginate(request, entries, 50)
    return render(request, 'audit/audit_list.html', {'form': form, 'page': page, 'qs': qs})