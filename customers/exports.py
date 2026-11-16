import jdatetime
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADERS = [
    'شناسه اشتراک', 'نام مشترک', 'موبایل', 'آدرس',
    'شهر', 'مرکز', 'تاریخ ثبت‌نام', 'وضعیت',
]
COLUMN_WIDTHS = [16, 26, 16, 45, 14, 22, 22, 45]


def _jalali_text(dt):
    """Same format the import expects: HH:MM:SS-YYYY/MM/DD, in local time."""
    local = timezone.localtime(dt).replace(tzinfo=None)
    return jdatetime.datetime.fromgregorian(datetime=local).strftime('%H:%M:%S-%Y/%m/%d')

def build_customers_workbook(customers):
    wb = Workbook()
    ws = wb.active
    ws.title = 'مشتریان'
    ws.sheet_view.rightToLeft = True

    # Row 1: when this file was generated (merged across all columns)
    now_local = timezone.localtime(timezone.now()).replace(tzinfo=None)
    generated = jdatetime.datetime.fromgregorian(datetime=now_local).strftime('%Y/%m/%d %H:%M')
    ws.append([f'آخرین بروزرسانی: {generated}'])
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(HEADERS))
    ws['A1'].font = Font(bold=True, color='555555')
    ws['A1'].alignment = Alignment(horizontal='right', vertical='center')

    # Row 2: column headers
    ws.append(HEADERS)
    for cell in ws[2]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill('solid', fgColor='E8EEF7')
        cell.alignment = Alignment(horizontal='center', vertical='center')

    # Row 3 onward: one row per customer
    for c in customers:
        ws.append([
            int(c.subscription_id),
            c.full_name,
            c.mobile,
            c.address,
            c.city.name,
            c.center,
            _jalali_text(c.registered_at),
            c.current_status_display(),
        ])

    for row in ws.iter_rows(min_row=3):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical='top')

    for index, width in enumerate(COLUMN_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width

    ws.freeze_panes = 'A3'  # keep the timestamp and headers visible while scrolling
    return wb