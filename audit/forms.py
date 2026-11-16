from django import forms

from accounts.jalali_forms import JalaliDateField

from .models import AuditEntry


class AuditFilterForm(forms.Form):
    action = forms.ChoiceField(
        label='نوع رویداد', required=False,
        choices=[('', 'همه')] + AuditEntry.Action.choices,
    )
    q = forms.CharField(label='جستجو (کاربر، مورد یا توضیح)', required=False)
    date_from = JalaliDateField(label='از تاریخ', required=False)
    date_to = JalaliDateField(label='تا تاریخ', required=False)