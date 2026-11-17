import jdatetime
from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def jalali(value, fmt='%Y/%m/%d %H:%M'):
    """Render a Gregorian date/datetime as a Jalali (Persian) calendar string."""
    if not value:
        return ''
    if timezone.is_aware(value):
        value = timezone.localtime(value).replace(tzinfo=None)
    if hasattr(value, 'hour'):
        jd = jdatetime.datetime.fromgregorian(datetime=value)
    else:
        jd = jdatetime.date.fromgregorian(date=value)
    return jd.strftime(fmt)






PERSIAN_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')

TIME_UNITS = (
    (365 * 86400, 'سال'),
    (30 * 86400, 'ماه'),
    (86400, 'روز'),
    (3600, 'ساعت'),
    (60, 'دقیقه'),
)


@register.filter
def time_ago(value):
    """Relative time in Persian, using only the largest unit: ۳ ساعت پیش, ۲ روز پیش."""
    if not value:
        return ''
    seconds = int((timezone.now() - value).total_seconds())
    for unit_seconds, name in TIME_UNITS:
        if seconds >= unit_seconds:
            return f'{seconds // unit_seconds} {name} پیش'.translate(PERSIAN_DIGITS)
    return 'لحظاتی پیش'