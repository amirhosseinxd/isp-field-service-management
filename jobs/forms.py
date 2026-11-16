from django import forms
from decimal import Decimal, InvalidOperation
from .models import Job, JobEvidence
from accounts.models import User

from inventory.models import Material
from accounts.jalali_forms import JalaliDateField
from customers.models import Customer
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
        label='دسته اصلی', required=False,
        choices=[('', 'همه')] + Job.JobType.choices,
    )
    workflow = forms.ChoiceField(
        label='نوع کار', required=False,
        choices=[('', 'همه')] + Job.Workflow.choices,
    )
    operator = OperatorChoiceField(
        label='تکنسین', required=False, empty_label='همه', queryset=operators(),
    )
    date_from = JalaliDateField(label='ارسال از تاریخ', required=False)
    date_to = JalaliDateField(label='ارسال تا تاریخ', required=False)


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
    date_from = JalaliDateField(label='آپلود از تاریخ', required=False)
    date_to = JalaliDateField(label='آپلود تا تاریخ', required=False)



YES_NO_CHOICES = [('True', 'بله'), ('False', 'خیر')]


class YesNoQuestionForm(forms.Form):
    answer = forms.TypedChoiceField(
        label='پاسخ', choices=YES_NO_CHOICES,
        coerce=lambda value: value == 'True',
        widget=forms.RadioSelect,
    )


class FtthOutcomeForm(forms.Form):
    answer = forms.ChoiceField(
        label='نتیجه', choices=Job.FtthOutcome.choices, widget=forms.RadioSelect,
    )


class SpeedQuestionForm(forms.Form):
    answer = forms.DecimalField(
        label='سرعت (Mbps)', min_value=Decimal('0.01'),
        max_digits=7, decimal_places=2,
        widget=forms.TextInput(attrs={'class': 'ltr', 'inputmode': 'decimal'}),
    )




class MaterialsSelectionForm(forms.Form):
    """One checkbox and one quantity box per allowed material, built at runtime."""

    def __init__(self, *args, materials, step, **kwargs):
        super().__init__(*args, **kwargs)
        self.step = step
        self.materials = list(materials)
        self.selected = []
        for m in self.materials:
            self.fields[f'select_{m.code}'] = forms.BooleanField(required=False, label=m.name)
            mode = 'decimal' if m.unit == Material.UNIT_METER else 'numeric'
            self.fields[f'qty_{m.code}'] = forms.DecimalField(
                required=False, min_value=Decimal('0.01'),
                max_digits=10, decimal_places=2,
                widget=forms.TextInput(attrs={
                    'class': 'ltr', 'inputmode': mode, 'placeholder': m.unit,
                }),
                label=m.name,
            )

    @property
    def rows(self):
        """(material, checkbox, quantity) for each material, for the template loop."""
        return [(m, self[f'select_{m.code}'], self[f'qty_{m.code}']) for m in self.materials]

    def clean(self):
        cleaned = super().clean()
        selected = []
        for m in self.materials:
            if not cleaned.get(f'select_{m.code}'):
                continue
            quantity = cleaned.get(f'qty_{m.code}')
            if quantity is None:
                self.add_error(f'qty_{m.code}', f'مقدار {m.name} را وارد کنید.')
                continue
            if m.unit == Material.UNIT_PIECE and quantity != quantity.to_integral_value():
                self.add_error(f'qty_{m.code}', 'برای این ماده فقط عدد صحیح مجاز است.')
                continue
            selected.append((m, quantity))

        self.selected = selected
        if not self.errors:
            problem = self.step.problem([m.code for m, _ in selected])
            if problem:
                raise forms.ValidationError(problem)
        return cleaned





class CustomerChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, customer):
        return f'{customer.full_name} — {customer.subscription_id} — {customer.city.name}'


class JobCreateForm(forms.ModelForm):
    assigned_operator = OperatorChoiceField(label='تکنسین', queryset=operators())
    customer = CustomerChoiceField(
        label='مشترک', queryset=Customer.objects.select_related('city'),
    )

    class Meta:
        model = Job
        fields = ['job_type', 'workflow', 'assigned_operator', 'customer']
        labels = {
            'job_type': 'دسته اصلی',
            'workflow': 'نوع کار',
        }



class ReturnForm(forms.Form):
    reason = forms.CharField(
        label='دلیل برگشت برای اصلاح', max_length=1000,
        widget=forms.Textarea(attrs={'rows': 3}),
    )