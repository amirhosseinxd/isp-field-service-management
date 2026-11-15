from django import forms
from decimal import Decimal, InvalidOperation
from .models import Job, JobEvidence
from accounts.models import User


MAX_PHOTO_MB = 15
MAX_FILES_PER_UPLOAD = 10
MAX_PHOTOS_PER_STAGE = 20

MAX_VIDEO_MB = 60
ALLOWED_VIDEO_TYPES = {'video/mp4', 'video/quicktime', 'video/webm'}

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




class MultipleFileInput(forms.FileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    """An image field that accepts several files and returns a list."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', MultipleFileInput(attrs={'accept': 'image/*'}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        clean_one = super().clean
        if isinstance(data, (list, tuple)):
            return [clean_one(item, initial) for item in data]
        return [clean_one(data, initial)]


class PhotoForm(forms.Form):
    images = MultipleImageField()

    def clean_images(self):
        images = self.cleaned_data['images']
        if len(images) > MAX_FILES_PER_UPLOAD:
            raise forms.ValidationError(
                f'در هر بار آپلود حداکثر {MAX_FILES_PER_UPLOAD} عکس مجاز است.'
            )
        for image in images:
            if image.size > MAX_PHOTO_MB * 1024 * 1024:
                raise forms.ValidationError('حجم هر عکس نباید بیشتر از ۱۵ مگابایت باشد.')
        return images


class VideoForm(forms.Form):
    video = forms.FileField(widget=forms.FileInput(attrs={'accept': 'video/*'}))

    def clean_video(self):
        video = self.cleaned_data['video']
        if video.size > MAX_VIDEO_MB * 1024 * 1024:
            raise forms.ValidationError(f'حجم ویدیو نباید بیشتر از {MAX_VIDEO_MB} مگابایت باشد.')
        if video.content_type not in ALLOWED_VIDEO_TYPES:
            raise forms.ValidationError('فرمت ویدیو پشتیبانی نمی‌شود. فرمت‌های مجاز: mp4, mov, webm.')
        return video

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
    category = forms.ChoiceField(
        label='مرحله', required=False,
        choices=[('', 'همه')] + [
            choice for choice in JobEvidence.Category.choices
            if choice[0] != JobEvidence.Category.VIDEO
        ],
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