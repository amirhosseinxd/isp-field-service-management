from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import SetPasswordForm

from accounts.models import User

from .rules import creatable_roles, is_owner, unfinished_jobs

LABELS = {
    'username': 'نام کاربری', 'first_name': 'نام', 'last_name': 'نام خانوادگی',
    'phone': 'شماره تلفن', 'role': 'نقش',
    'can_manage_accounts': 'می‌تواند حساب‌های پشتیبان بسازد و مدیریت کند',
}
HELP_TEXTS = {
    'username': 'برای ورود استفاده می‌شود؛ ترجیحاً انگلیسی و بدون فاصله.',
    'can_manage_accounts': 'فقط برای نقش پشتیبان. این گزینه فقط برای مالک دیده می‌شود.',
}


class _UserForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'phone', 'role', 'can_manage_accounts']
        labels = LABELS
        help_texts = HELP_TEXTS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True

    def clean_username(self):
        username = self.cleaned_data['username']
        clash = User.objects.filter(username__iexact=username).exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError('این نام کاربری قبلاً استفاده شده است.')
        return username


class UserCreateForm(_UserForm):
    password1 = forms.CharField(
        label='رمز عبور', strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        help_text=password_validation.password_validators_help_text_html(),
    )
    password2 = forms.CharField(
        label='تکرار رمز عبور', strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
    )

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        allowed = creatable_roles(actor)
        self.fields['role'].choices = [(v, l) for v, l in User.Role.choices if v in allowed]
        if not is_owner(actor):
            # The field does not exist for anyone else, so a hand-made POST can't set it
            del self.fields['can_manage_accounts']

    def clean_role(self):
        role = self.cleaned_data['role']
        if role not in creatable_roles(self.actor):
            raise forms.ValidationError('شما اجازه ساخت این نوع حساب را ندارید.')
        return role

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get('password1'), cleaned.get('password2')
        if p1 and p2 and p1 != p2:
            self.add_error('password2', 'دو رمز عبور یکسان نیستند.')
        elif p1:
            candidate = User(
                username=cleaned.get('username', ''),
                first_name=cleaned.get('first_name', ''),
                last_name=cleaned.get('last_name', ''),
            )
            try:
                password_validation.validate_password(p1, candidate)
            except forms.ValidationError as error:
                self.add_error('password1', error)
        if 'can_manage_accounts' in self.fields and cleaned.get('role') != User.Role.ADMIN:
            cleaned['can_manage_accounts'] = False     # technicians never get it
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        user.is_staff = False          # this screen can never grant Django-admin powers
        user.is_superuser = False
        if commit:
            user.save()
        return user


class UserEditForm(_UserForm):
    confirm_role_change = forms.BooleanField(required=False, label='متوجه‌ام و تغییر نقش را تأیید می‌کنم')

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        target = self.instance
        self.old_role = target.role
        editing_self = target.pk == actor.pk

        if editing_self:
            # A disabled field ignores whatever the browser posts
            self.fields['username'].disabled = True
            self.fields['username'].help_text = 'نام کاربری خودتان را نمی‌توانید تغییر دهید.'

        # Role and "manage accounts": the owner only, for someone else, never for Django-admin accounts
        self.can_change_access = (
            is_owner(actor) and not editing_self and not (target.is_superuser or target.is_staff)
        )
        if not self.can_change_access:
            for name in ('role', 'can_manage_accounts', 'confirm_role_change'):
                del self.fields[name]

    def clean(self):
        cleaned = super().clean()
        if not self.can_change_access:
            return cleaned
        new_role = cleaned.get('role')
        if new_role and new_role != self.old_role:
            if not cleaned.get('confirm_role_change'):
                self.add_error('confirm_role_change', 'برای تغییر نقش، این گزینه را تأیید کنید.')
            if new_role == User.Role.ADMIN:
                count = unfinished_jobs(self.instance).count()
                if count:
                    self.add_error(
                        'role',
                        f'این تکنسین {count} کار ناتمام دارد. ابتدا آن‌ها را به تکنسین دیگری ارجاع دهید.',
                    )
        if cleaned.get('role') == User.Role.OPERATOR:
            cleaned['can_manage_accounts'] = False
        return cleaned


class AdminSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['new_password1'].label = 'رمز عبور جدید'
        self.fields['new_password2'].label = 'تکرار رمز عبور جدید'


class UserFilterForm(forms.Form):
    q = forms.CharField(
        label='جستجو', required=False,
        widget=forms.TextInput(attrs={'placeholder': 'نام، نام کاربری یا تلفن'}),
    )
    role = forms.ChoiceField(label='نقش', required=False, choices=[('', 'همه')] + list(User.Role.choices))
    status = forms.ChoiceField(
        label='وضعیت حساب', required=False,
        choices=[('', 'همه'), ('active', 'فعال'), ('inactive', 'غیرفعال')],
    )