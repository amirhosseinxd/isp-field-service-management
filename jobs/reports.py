from collections import defaultdict
from datetime import timedelta

from django.db.models import Count, Prefetch, Q
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from accounts.models import User
from accounts.templatetags.jalali_tags import jalali

from .models import Job, JobMaterialUsage

SUMMARY_SHEET = 'خلاصه عملکرد تکنسین‌ها'
DETAIL_SHEET = 'گزارش تفصیلی کارها'

SUMMARY_HEADERS = [
    'نام تکنسین', 'کل کارهای ارجاع‌شده', 'کارهای انجام‌شده', 'کارهای تأییدشده',
    'کارهای برگشتی', 'کارهای در حال انجام', 'میانگین زمان انجام کار',
]
DETAIL_HEADERS = [
    'شناسه کار', 'نام تکنسین', 'نام مشترک', 'دسته اصلی', 'نوع کار', 'وضعیت فعلی',
    'تاریخ ارجاع', 'تاریخ ارسال', 'تاریخ بررسی', 'متریال مصرفی', 'زمان کل انجام کار',
]
SUMMARY_WIDTHS = [26, 16, 16, 16, 16, 18, 22]
DETAIL_WIDTHS = [10, 22, 24, 16, 18, 18, 18, 18, 18, 45, 22]

SUMMARY_NOTE = (
    'انجام‌شده: حداقل یک بار ارسال شده · تأییدشده: بررسی و تأیید شده · '
    'برگشتی: حداقل یک بار برای اصلاح برگشت داده شده · در حال انجام: هنوز ارسال نشده · '
    'میانگین: از ارجاع تا ارسال، فقط کارهای ارسال‌شده'
)
DETAIL_NOTE = 'متریال مصرفی فقط موارد استفاده‌شده را نشان می‌دهد · زمان کل: از ارجاع تا آخرین ارسال'


def person_name(user):
    return user.get_full_name() or user.username


def format_duration(delta):
    """A readable duration, for example '2 روز و 3 ساعت'."""
    seconds = max(int(delta.total_seconds()), 0)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        result = f'{days} روز و {hours} ساعت' if hours else f'{days} روز'
    elif hours:
        result = f'{hours} ساعت و {minutes} دقیقه' if minutes else f'{hours} ساعت'
    elif minutes:
        result = f'{minutes} دقیقه'
    else:
        result = 'کمتر از 1 دقیقه'

    return f'\u200f{result}\u200f'

def materials_text(usages):
    parts = []
    for usage in usages:
        quantity = format(usage.quantity.normalize(), 'f')  # 12.50 -> 12.5, 2.00 -> 2
        parts.append(f'{usage.material_name} {quantity} {usage.unit}')
    return '، '.join(parts)


def collect_report(date_from=None, date_to=None):
    """All the numbers for both sheets, for jobs assigned between the two dates."""
    jobs = (
        Job.objects.select_related('assigned_operator', 'customer')
        .prefetch_related(Prefetch(
            'material_usages',
            queryset=JobMaterialUsage.objects.filter(purpose=JobMaterialUsage.Purpose.USED),
            to_attr='used_materials',
        ))
        .annotate(return_count=Count('returns', distinct=True))
    )
    if date_from:
        jobs = jobs.filter(created_at__date__gte=date_from)
    if date_to:
        jobs = jobs.filter(created_at__date__lte=date_to)
    jobs = list(jobs)

    by_technician = defaultdict(list)
    for job in jobs:
        by_technician[job.assigned_operator_id].append(job)

    technicians = User.objects.filter(role=User.Role.OPERATOR).filter(
        Q(is_active=True) | Q(pk__in=list(by_technician))
    )

    summary = []
    for technician in sorted(technicians, key=person_name):
        mine = by_technician.get(technician.pk, [])
        submitted = [job for job in mine if job.submitted_at]
        durations = [max(job.submitted_at - job.created_at, timedelta()) for job in submitted]
        summary.append({
            'name': person_name(technician),
            'total': len(mine),
            'completed': len(submitted),
            'approved': sum(1 for job in mine if job.status == Job.Status.REVIEWED),
            'returned': sum(1 for job in mine if job.return_count > 0),
            'in_progress': len(mine) - len(submitted),
            'average': sum(durations, timedelta()) / len(durations) if durations else None,
        })

    details = []
    for job in sorted(jobs, key=lambda j: (person_name(j.assigned_operator), j.created_at)):
        details.append({
            'id': job.pk,
            'technician': person_name(job.assigned_operator),
            'customer': job.customer.full_name if job.customer else '',
            'category': job.get_job_type_display(),
            'workflow': job.get_workflow_display(),
            'status': job.get_status_display(),
            'assigned': job.created_at,
            'submitted': job.submitted_at,
            'reviewed': job.reviewed_at,
            'materials': materials_text(job.used_materials),
            'duration': (
                max(job.submitted_at - job.created_at, timedelta()) if job.submitted_at else None
            ),
        })
    return {'summary': summary, 'details': details}


def period_text(date_from, date_to):
    start = jalali(date_from, '%Y/%m/%d') if date_from else 'ابتدا'
    end = jalali(date_to, '%Y/%m/%d') if date_to else 'امروز'
    return f'از {start} تا {end}'


def _write_sheet(ws, title, note, headers, rows, widths):
    columns = len(headers)
    ws.sheet_view.rightToLeft = True

    ws.append([title])
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=columns)
    ws['A1'].font = Font(bold=True, size=12)
    ws['A1'].alignment = Alignment(horizontal='right', vertical='center')

    ws.append([note])
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=columns)
    ws['A2'].font = Font(color='666666', size=10)
    ws['A2'].alignment = Alignment(horizontal='right', vertical='center', wrap_text=True)
    ws.row_dimensions[2].height = 30

    ws.append(headers)
    for cell in ws[3]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill('solid', fgColor='E8EEF7')
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

    for row in rows:
        ws.append(row)
    for row in ws.iter_rows(min_row=4):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical='top')

    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.freeze_panes = 'A4'

    # Text such as "=1+1" typed into a customer name would otherwise run as a formula in Excel
    for row in ws.iter_rows():
        for cell in row:
            if cell.data_type == 'f':
                cell.data_type = 's'


def build_report_workbook(report, date_from, date_to):
    wb = Workbook()
    summary_ws = wb.active
    summary_ws.title = SUMMARY_SHEET
    detail_ws = wb.create_sheet(DETAIL_SHEET)

    header = f'بازه ارجاع: {period_text(date_from, date_to)} | تهیه‌شده در: {jalali(timezone.now())}'

    summary_rows = [
        [
            r['name'], r['total'], r['completed'], r['approved'], r['returned'],
            r['in_progress'],
            format_duration(r['average']) if r['average'] is not None else None,
        ]
        for r in report['summary']
    ]
    _write_sheet(
        summary_ws, f'گزارش عملکرد تکنسین‌ها | {header}', SUMMARY_NOTE,
        SUMMARY_HEADERS, summary_rows, SUMMARY_WIDTHS,
    )

    detail_rows = [
        [
            d['id'], d['technician'], d['customer'] or None, d['category'], d['workflow'],
            d['status'], jalali(d['assigned']) or None, jalali(d['submitted']) or None,
            jalali(d['reviewed']) or None, d['materials'] or None,
            format_duration(d['duration']) if d['duration'] is not None else None,
        ]
        for d in report['details']
    ]
    _write_sheet(
        detail_ws, f'گزارش تفصیلی کارها | {header}', DETAIL_NOTE,
        DETAIL_HEADERS, detail_rows, DETAIL_WIDTHS,
    )
    return wb