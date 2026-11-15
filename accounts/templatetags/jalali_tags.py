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