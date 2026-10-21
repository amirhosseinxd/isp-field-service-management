from django import forms
from decimal import Decimal, InvalidOperation
from .models import Job, JobPhoto

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