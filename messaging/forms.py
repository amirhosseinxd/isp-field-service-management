from django import forms

from accounts.models import User

SUBJECT_MAX = 120
BODY_MAX = 2000


class ReplyForm(forms.Form):
    body = forms.CharField(
        label='پیام', max_length=BODY_MAX,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'پاسخ خود را بنویسید…'}),
    )


class TechnicianComposeForm(forms.Form):
    subject = forms.CharField(label='موضوع', max_length=SUBJECT_MAX)
    body = forms.CharField(label='متن پیام', max_length=BODY_MAX, widget=forms.Textarea(attrs={'rows': 6}))


class SupportComposeForm(TechnicianComposeForm):
    recipient = forms.ChoiceField(label='گیرنده')
    field_order = ['recipient', 'subject', 'body']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        technicians = User.objects.filter(role=User.Role.OPERATOR, is_active=True).order_by(
            'first_name', 'last_name', 'username',
        )
        self.technicians = {str(u.pk): u for u in technicians}
        choices = [(pk, f'{u.display_name} ({u.username})') for pk, u in self.technicians.items()]
        if self.technicians:
            choices.insert(0, ('all', 'همه تکنسین‌ها (اطلاعیه)'))
        self.fields['recipient'].choices = choices      # inactive technicians are not offered, and not accepted