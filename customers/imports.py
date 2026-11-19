import re
from datetime import datetime, time

import jdatetime
from django.utils import timezone

from .models import City, Customer

# Column letters in the real Excel files, fixed and non-contiguous
COLUMNS = {
    'subscription_id': 'C',
    'full_name': 'D',
    'mobile': 'F',
    'address': 'G',
    'city': 'P',
    'center': 'Q',
    'registered_at': 'AA',
    'status': 'AD',
}

CENTER_NUMBER_RE = re.compile(r'OAC\.(\d{1,2})')
JALALI_RE = re.compile(r'^(\d{2}):(\d{2}):(\d{2})-(\d{3,4})/(\d{1,2})/(\d{1,2})$')


class RowError(Exception):
    """Raised when one row's data can't be used; the row is skipped, not the whole import."""


def _clean_subscription_id(value):
    if value in (None, ''):
        raise RowError('شناسه اشتراک خالی است.')
    if isinstance(value, float):
        value = int(value)
    text = str(value).strip()
    if not text.isdigit():
        raise RowError(f'شناسه اشتراک نامعتبر است: {value!r}')
    text = text.zfill(10)
    if len(text) != 10:
        raise RowError(f'شناسه اشتراک بیش از ۱۰ رقم است: {value!r}')
    return text


def _clean_mobile(value):
    if value in (None, ''):
        return ''
    if isinstance(value, float):
        value = int(value)
    text = str(value).strip()
    if text.isdigit() and len(text) == 10:
        text = '0' + text  # Excel drops Iranian mobile numbers' leading 0
    return text

def normalize_name(text):
    """A spelling-insensitive form of a name: ignores spaces and half-spaces, unifies ی/ي and ک/ك."""
    text = str(text or '').replace('\u064A', '\u06CC').replace('\u0643', '\u06A9')
    for character in (' ', '\u200c', '\u200e', '\u200f', '\u00a0'):
        text = text.replace(character, '')
    return text.lower()


def city_lookup():
    """Every city, keyed by its normalized name."""
    return {normalize_name(city.name): city for city in City.objects.all()}


def _clean_city(value, cities):
    name = str(value).strip() if value is not None else ''
    city = cities.get(normalize_name(name))
    if city is None:
        raise RowError(f'شهر نامعتبر یا خارج از فهرست ثابت: {name!r}')
    return city


def _clean_center_number(value):
    text = str(value).strip() if value is not None else ''
    match = CENTER_NUMBER_RE.search(text)
    if not match:
        raise RowError(f'فرمت مرکز قابل تشخیص نیست: {text!r}')
    return match.group(1).zfill(2)


def _clean_registered_at(value):
    text = str(value).strip() if value is not None else ''
    match = JALALI_RE.match(text)
    if not match:
        raise RowError(f'تاریخ ثبت‌نام قابل خواندن نیست (فرمت مورد انتظار: HH:MM:SS-YYYY/MM/DD): {text!r}')

    hour, minute, second, jyear, jmonth, jday = (int(g) for g in match.groups())
    try:
        gregorian_date = jdatetime.date(jyear, jmonth, jday).togregorian()
    except ValueError:
        raise RowError(f'تاریخ شمسی نامعتبر است: {text!r}')

    dt = datetime.combine(gregorian_date, time(hour, minute, second))
    return timezone.make_aware(dt)


def parse_row(values, cities=None):
    """values: a dict with the keys in COLUMNS, already read from one Excel row."""
    cities = cities if cities is not None else city_lookup()
    subscription_id = _clean_subscription_id(values['subscription_id'])
    full_name = str(values['full_name']).strip() if values['full_name'] not in (None, '') else ''
    mobile = _clean_mobile(values['mobile'])
    address = str(values['address']).strip() if values['address'] not in (None, '') else ''
    city = _clean_city(values['city'], cities)
    center_number = _clean_center_number(values['center'])
    registered_at = _clean_registered_at(values['registered_at'])
    status_label = str(values['status']).strip() if values['status'] not in (None, '') else ''

    if not full_name:
        raise RowError('نام مشترک خالی است.')

    return {
        'subscription_id': subscription_id,
        'full_name': full_name,
        'mobile': mobile,
        'address': address,
        'city': city,
        'center_number': center_number,
        'registered_at': registered_at,
        'status_label': status_label,
    }


def import_rows(rows):
    """rows: iterable of (row_number, values_dict). Returns a summary dict."""
    created = 0
    updated = 0
    errors = []
    cities = city_lookup() # built once, not once per row

    for row_number, values in rows:
        if all(v in (None, '') for v in values.values()):
            continue  # a fully blank row, skip quietly

        try:
            data = parse_row(values, cities)
        except RowError as exc:
            errors.append((row_number, str(exc)))
            continue

        subscription_id = data.pop('subscription_id')
        _, was_created = Customer.objects.update_or_create(
            subscription_id=subscription_id, defaults=data,
        )
        if was_created:
            created += 1
        else:
            updated += 1

    return {'created': created, 'updated': updated, 'errors': errors}