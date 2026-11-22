from collections import defaultdict
from decimal import Decimal

import jdatetime
from django.db.models import Sum
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from inventory.models import Material
from jobs.models import Job, JobMaterialUsage
from accounts.templatetags.jalali_tags import jalali

HEADERS = [
    'شناسه اشتراک', 'نام مشترک', 'موبایل', 'آدرس',
    'شهر', 'مرکز', 'تاریخ ثبت‌نام', 'تاریخ آخرین تغییر', 'وضعیت',
]
COLUMN_WIDTHS = [16, 26, 16, 45, 14, 22, 22, 22, 45]
MATERIAL_COLUMN_WIDTH = 16
BILLABLE_STATUSES = (Job.Status.SUBMITTED, Job.Status.REVIEWED)


def _jalali_text(dt):
    """Same format the import expects: HH:MM:SS-YYYY/MM/DD, in local time."""
    local = timezone.localtime(dt).replace(tzinfo=None)
    return jdatetime.datetime.fromgregorian(datetime=local).strftime('%H:%M:%S-%Y/%m/%d')


def material_totals_by_customer():
    """{customer_id: {material_code: total_quantity}} over all billable jobs."""
    rows = (
        JobMaterialUsage.objects
        .filter(
            purpose=JobMaterialUsage.Purpose.USED,
            job__customer__isnull=False,
            job__status__in=BILLABLE_STATUSES,
        )
        .order_by()  # clears the model's default ordering, which would break the grouping
        .values('job__customer_id', 'material_code')
        .annotate(total=Sum('quantity'))
    )
    totals = defaultdict(dict)
    for row in rows:
        totals[row['job__customer_id']][row['material_code']] = row['total']
    return totals


def build_customers_workbook(customers):
    materials = list(Material.objects.order_by('code'))
    totals = material_totals_by_customer()

    headers = HEADERS + [f'{m.name} ({m.unit})' for m in materials]
    last_column = len(headers)

    wb = Workbook()
    ws = wb.active
    ws.title = 'مشتریان'
    ws.sheet_view.rightToLeft = True

    # Row 1: when this file was generated
    now_local = timezone.localtime(timezone.now()).replace(tzinfo=None)
    generated = jdatetime.datetime.fromgregorian(datetime=now_local).strftime('%Y/%m/%d %H:%M')
    ws.append([f'آخرین بروزرسانی: {generated}'])
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_column)
    ws['A1'].font = Font(bold=True, color='555555')
    ws['A1'].alignment = Alignment(horizontal='right', vertical='center')

    # Row 2: column headers
    ws.append(headers)
    for cell in ws[2]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill('solid', fgColor='E8EEF7')
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

    # Row 3 onward: one row per customer
    for c in customers:
        customer_totals = totals.get(c.pk, {})
        ws.append([
            int(c.subscription_id),
            c.full_name,
            c.mobile,
            c.address,
            c.city.name,
            c.center,
            _jalali_text(c.registered_at),
            jalali(getattr(c, 'last_change', None)) or None,
            c.current_status_display(),
        ] + [
            float(customer_totals[m.code]) if m.code in customer_totals else None
            for m in materials
        ])

    for row in ws.iter_rows(min_row=3):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical='top')

    widths = COLUMN_WIDTHS + [MATERIAL_COLUMN_WIDTH] * len(materials)
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width

    ws.freeze_panes = 'A3'
    return wb