from django import forms
from django.db.models import Q

from .models import City, Customer


class CustomerForm(forms.ModelForm):
    registered_at = forms.DateTimeField(
        label='تاریخ و ساعت ثبت‌نام',
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
        input_formats=['%Y-%m-%dT%H:%M'],
    )

    class Meta:
        model = Customer
        fields = [
            'subscription_id', 'full_name', 'mobile', 'address',
            'city', 'center_number', 'registered_at', 'status_label',
        ]
        labels = {
            'subscription_id': 'شناسه اشتراک',
            'full_name': 'نام مشترک',
            'mobile': 'موبایل',
            'address': 'آدرس',
            'city': 'شهر',
            'center_number': 'شماره مرکز',
            'registered_at': 'تاریخ ثبتنام',
            'status_label': 'وضعیت (در صورت نبود کار ثبت‌شده)',
        }
        widgets = {
            'subscription_id': forms.TextInput(attrs={'class': 'ltr', 'inputmode': 'numeric'}),
            'mobile': forms.TextInput(attrs={'class': 'ltr', 'inputmode': 'tel'}),
            'center_number': forms.TextInput(attrs={'class': 'ltr', 'inputmode': 'numeric'}),
            'address': forms.Textarea(attrs={'rows': 3}),
        }


class CustomerFilterForm(forms.Form):
    q = forms.CharField(label='جستجو (شناسه، نام یا موبایل)', required=False)
    city = forms.ModelChoiceField(
        label='شهر', queryset=City.objects.all(), required=False, empty_label='همه',
    )