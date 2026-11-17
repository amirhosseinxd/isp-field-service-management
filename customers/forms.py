from django import forms
from django.db.models import Q

from .models import City, Customer
from accounts.jalali_forms import JalaliDateTimeField
from .filters import material_choices
class CustomerForm(forms.ModelForm):
    registered_at = JalaliDateTimeField(label='تاریخ و ساعت ثبت‌نام')

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
    material = forms.ChoiceField(label='متریال مصرف‌شده', required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Built when the form is created, so it always matches the materials table
        self.fields['material'].choices = material_choices()





class ExcelUploadForm(forms.Form):
    excel_file = forms.FileField(label='فایل اکسل (.xlsx)')

    def clean_excel_file(self):
        file = self.cleaned_data['excel_file']
        if not file.name.lower().endswith('.xlsx'):
            raise forms.ValidationError('فقط فایل‌های با پسوند xlsx پذیرفته می‌شود.')
        return file