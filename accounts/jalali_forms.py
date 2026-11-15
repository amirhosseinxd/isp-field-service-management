from datetime import datetime, time

import jdatetime
from django import forms
from django.utils import timezone

PERSIAN_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


class JalaliDateField(forms.CharField):
    """A text field, paired with a Jalali calendar picker, that stores a Gregorian date."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', forms.TextInput(attrs={
            'class': 'jalali-date ltr', 'autocomplete': 'off', 'placeholder': '۱۴۰۵/۰۸/۲۴',
        }))
        super().__init__(*args, **kwargs)

    def prepare_value(self, value):
        if not value:
            return ''
        if isinstance(value, str):
            return value
        return jdatetime.date.fromgregorian(date=value).strftime('%Y/%m/%d')

    def to_python(self, value):
        value = super().to_python(value)
        if not value:
            return None
        value = value.translate(PERSIAN_DIGITS).strip()
        try:
            year, month, day = (int(part) for part in value.split('/'))
            return jdatetime.date(year, month, day).togregorian()
        except (ValueError, TypeError):
            raise forms.ValidationError('تاریخ معتبر نیست. فرمت صحیح: ۱۴۰۵/۰۸/۲۴')


class JalaliDateTimeField(forms.CharField):
    """A text field, paired with a Jalali calendar+time picker, that stores an aware Gregorian datetime."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', forms.TextInput(attrs={
            'class': 'jalali-datetime ltr', 'autocomplete': 'off', 'placeholder': '۱۴۰۵/۰۸/۲۴ ۱۴:۳۰',
        }))
        super().__init__(*args, **kwargs)

    def prepare_value(self, value):
        if not value:
            return ''
        if isinstance(value, str):
            return value
        if timezone.is_aware(value):
            value = timezone.localtime(value).replace(tzinfo=None)
        return jdatetime.datetime.fromgregorian(datetime=value).strftime('%Y/%m/%d %H:%M')

    def to_python(self, value):
        value = super().to_python(value)
        if not value:
            return None
        value = value.translate(PERSIAN_DIGITS).strip()
        try:
            date_part, time_part = value.split(' ')
            year, month, day = (int(part) for part in date_part.split('/'))
            hour, minute = (int(part) for part in time_part.split(':'))
        except (ValueError, TypeError):
            raise forms.ValidationError('تاریخ/ساعت معتبر نیست. فرمت صحیح: ۱۴۰۵/۰۸/۲۴ ۱۴:۳۰')
        try:
            gregorian_date = jdatetime.date(year, month, day).togregorian()
        except ValueError:
            raise forms.ValidationError('تاریخ شمسی نامعتبر است.')
        dt = datetime.combine(gregorian_date, time(hour, minute))
        return timezone.make_aware(dt)