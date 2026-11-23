from django.conf import settings
from django.db import models

from accounts.models import User

PREVIEW_LENGTH = 100


class Conversation(models.Model):
    class Kind(models.TextChoices):
        PRIVATE = 'private', 'گفت‌وگو'
        ANNOUNCEMENT = 'announcement', 'اطلاعیه'

    kind = models.CharField(max_length=20, choices=Kind.choices, db_index=True)
    # Private conversations only: the technician on the other side of the shared support inbox
    technician = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name='conversations',
    )
    subject = models.CharField(max_length=120)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    # These three are filled in by services._add_message, so lists need no extra queries
    last_message_at = models.DateTimeField(db_index=True)
    last_sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name='+',
    )
    last_preview = models.CharField(max_length=PREVIEW_LENGTH, blank=True)
    # Announcements: how many active technicians it was sent to, at that moment
    recipient_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-last_message_at', '-id']
        constraints = [
            models.CheckConstraint(
                name='conversation_technician_only_when_private',
                condition=(
                    models.Q(kind='private', technician__isnull=False)
                    | models.Q(kind='announcement', technician__isnull=True)
                ),
            ),
        ]

    def __str__(self):
        return self.subject

    @property
    def waiting_for_support(self):
        """A technician wrote last, so nobody from support has answered yet."""
        return (
            self.kind == self.Kind.PRIVATE
            and self.last_sender_id is not None
            and self.last_sender.role == User.Role.OPERATOR
        )


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.PROTECT, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='sent_messages')
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['created_at', 'id']

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError('پیام‌ها قابل ویرایش نیستند.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError('پیام‌ها قابل حذف نیستند.')


class ConversationRead(models.Model):
    """How far each person has read each conversation (a message id, not a time, so nothing is missed)."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='conversation_reads')
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='reads')
    last_read_message_id = models.BigIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'conversation'], name='one_read_marker_per_user_and_conversation'),
        ]