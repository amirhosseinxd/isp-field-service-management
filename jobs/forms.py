from django import forms
from decimal import Decimal, InvalidOperation
from .models import Job, JobPhoto
from accounts.models import User


MAX_PHOTO_MB = 15

PERSIAN_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')

class CoordinateField(forms.DecimalField):
    """Accepts Persian/Arabic digits and separators, rounds to 6 decimals."""

    def to_python(self, value):
        if isinstance(value, str):
            value = value.translate(PERSIAN_DIGITS).replace('٫', '.').replace(',', '.').strip()
        number = super().to_python(value)
        if number is None:
            return None
        try:
            return number.quantize(Decimal('0.000001'))
        except InvalidOperation:
            raise forms.ValidationError('مقدار وارد شده معتبر نیست.')



        
class LocationForm(forms.Form):
    latitude = CoordinateField(
        max_digits=9, decimal_places=6, min_value=-90, max_value=90,
        widget=forms.TextInput(attrs={'class': 'ltr', 'inputmode': 'decimal', 'placeholder': '35.689200'}),
    )
    longitude = CoordinateField(
        max_digits=9, decimal_places=6, min_value=-180, max_value=180,
        widget=forms.TextInput(attrs={'class': 'ltr', 'inputmode': 'decimal', 'placeholder': '51.389000'}),
    )
    source = forms.ChoiceField(
        choices=Job.LocationSource.choices, widget=forms.HiddenInput,
    )




class PhotoForm(forms.ModelForm):
    class Meta:
        model = JobPhoto
        fields = ['image']
        widgets = {
            'image': forms.FileInput(attrs={
                'accept': 'image/*',
            }),
        }

    def clean_image(self):
        image = self.cleaned_data['image']
        if image.size > MAX_PHOTO_MB * 1024 * 1024:
            raise forms.ValidationError('حجم عکس نباید بیشتر از ۱۵ مگابایت باشد.')
        return image




class ReportForm(forms.Form):
    description = forms.CharField(
        max_length=2000,
        widget=forms.Textarea(attrs={'rows': 5}),
    )





class OperatorChoiceField(forms.ModelChoiceField):
 def label_from_instance(self, user):
    return user.get_full_name() or user.username


def operators():
    return User.objects.filter(role=User.Role.OPERATOR)


class JobFilterForm(forms.Form):
    status = forms.ChoiceField(
        label='وضعیت', required=False,
        choices=[('', 'همه')] + Job.Status.choices,
    )
    job_type = forms.ChoiceField(
        label='نوع کار', required=False,
        choices=[('', 'همه')] + Job.JobType.choices,
    )
    operator = OperatorChoiceField(
        label='تکنسین', required=False, empty_label='همه', queryset=operators(),
    )
    date_from = forms.DateField(
        label='ارسال از تاریخ', required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    date_to = forms.DateField(
        label='ارسال تا تاریخ', required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
    )


class PhotoFilterForm(forms.Form):
    job = forms.IntegerField(label='شماره کار', required=False, min_value=1)
    stage = forms.ChoiceField(
        label='مرحله', required=False,
        choices=[('', 'همه')] + JobPhoto.Stage.choices,
    )
    operator = OperatorChoiceField(
        label='تکنسین', required=False, empty_label='همه', queryset=operators(),
    )
    date_from = forms.DateField(
        label='آپلود از تاریخ', required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    date_to = forms.DateField(
        label='آپلود تا تاریخ', required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
    )