from django.db.models import Max, Q

from inventory.models import Material
from jobs.models import JobMaterialUsage

from .exports import BILLABLE_STATUSES
from .models import Customer

from datetime import datetime, timezone as dt_timezone

from django.db.models import DateTimeField, Value
from django.db.models.functions import Coalesce, Greatest, NullIf


# Materials that are really one item, shown as a single filter option
MATERIAL_GROUPS = {
    'g_splitter': ('اسپلیتر', ('M012', 'M013')),
    'g_dastak': ('دستک', ('M007', 'M008')),
}


def material_choices():
    grouped = {code for _, codes in MATERIAL_GROUPS.values() for code in codes}
    choices = [('', 'همه')]
    choices += [(key, label) for key, (label, _) in MATERIAL_GROUPS.items()]
    choices += [
        (m.code, f'{m.name} ({m.unit})')
        for m in Material.objects.order_by('code')
        if m.code not in grouped
    ]
    return choices


def codes_for(choice):
    """The material codes behind one filter option (one code, or all codes of a group)."""
    if choice in MATERIAL_GROUPS:
        return MATERIAL_GROUPS[choice][1]
    return (choice,)


NEVER = datetime(1970, 1, 1, tzinfo=dt_timezone.utc)   # stands in for "no date" inside the query


def base_customers():
    never = Value(NEVER, output_field=DateTimeField())
    return (
        Customer.objects.select_related('city')
        .annotate(last_activity=Max('jobs__updated_at'))
        .annotate(last_change=NullIf(
            Greatest(
                Coalesce('last_modified_at', never),
                Coalesce('last_activity', never),
            ),
            never,
        ))
    )


def apply_filters(customers, form):
    if not form.is_valid():
        return customers
    cd = form.cleaned_data

    if cd['q']:
        q = cd['q']
        customers = customers.filter(
            Q(subscription_id__icontains=q)
            | Q(full_name__icontains=q)
            | Q(mobile__icontains=q)
        )
    if cd['city']:
        customers = customers.filter(city=cd['city'])
    if cd['material']:
        used_by = JobMaterialUsage.objects.filter(
            purpose=JobMaterialUsage.Purpose.USED,
            job__status__in=BILLABLE_STATUSES,
            job__customer__isnull=False,
            material_code__in=codes_for(cd['material']),
        ).values('job__customer_id')
        customers = customers.filter(pk__in=used_by)
    return customers