from django.db import transaction
from django.db.models import F, OuterRef, Q, Subquery
from django.utils import timezone

from accounts.models import User

from .models import PREVIEW_LENGTH, Conversation, ConversationRead, Message

PERSIAN_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')


def visible_conversations(user):
    """The ONLY place that decides who may see what. Every view starts from this."""
    if user.role == User.Role.ADMIN:
        return Conversation.objects.all()                       # the shared support inbox
    return Conversation.objects.filter(
        Q(kind=Conversation.Kind.ANNOUNCEMENT) | Q(technician=user)
    )


def can_reply(user, conversation):
    if conversation.kind != Conversation.Kind.PRIVATE:
        return False                                            # announcements are one-way
    if not conversation.technician.is_active:
        return False
    if user.role == User.Role.ADMIN:
        return True
    return conversation.technician_id == user.pk


def recipient_label(conversation, message):
    if conversation.kind == Conversation.Kind.ANNOUNCEMENT:
        return 'همهٔ تکنسین‌ها'
    if message.sender.role == User.Role.OPERATOR:
        return 'پشتیبانی'
    return conversation.technician.display_name


def unread_messages(user):
    """Messages `user` has not read. One definition, used by the badge, the lists and the highlights."""
    marker = ConversationRead.objects.filter(conversation=OuterRef('conversation'), user=user)
    found = Message.objects.annotate(last_read=Subquery(marker.values('last_read_message_id')[:1]))
    if user.role == User.Role.ADMIN:
        # Support: what technicians wrote. Another support's reply is not "unread" for you.
        found = found.filter(
            conversation__kind=Conversation.Kind.PRIVATE, sender__role=User.Role.OPERATOR,
        )
    else:
        # Technician: what others wrote in their own conversations, plus announcements
        found = found.filter(
            Q(conversation__kind=Conversation.Kind.ANNOUNCEMENT) | Q(conversation__technician=user)
        ).exclude(sender=user)
    # Never opened: only messages written after the account existed count (no pile of old messages)
    return found.filter(
        Q(last_read__isnull=False, id__gt=F('last_read'))
        | Q(last_read__isnull=True, created_at__gt=user.date_joined)
    )


def unread_count(user):
    return unread_messages(user).count()


def badge_text(count):
    return ('۹+' if count > 9 else str(count)).translate(PERSIAN_DIGITS)


def mark_read(user, conversation, message_id):
    marker, created = ConversationRead.objects.get_or_create(
        user=user, conversation=conversation, defaults={'last_read_message_id': message_id},
    )
    if not created and marker.last_read_message_id < message_id:
        marker.last_read_message_id = message_id
        marker.save(update_fields=['last_read_message_id'])


def newer_support_replies(conversation, user, after):
    """Did another support answer after the message id this page was showing?"""
    try:
        after = int(after)
    except (TypeError, ValueError):
        return False
    return conversation.messages.filter(
        id__gt=after, sender__role=User.Role.ADMIN,
    ).exclude(sender=user).exists()


def _add_message(conversation, sender, body):
    message = Message.objects.create(conversation=conversation, sender=sender, body=body)
    conversation.last_message_at = message.created_at
    conversation.last_sender = sender
    conversation.last_preview = ' '.join(body.split())[:PREVIEW_LENGTH]
    conversation.save(update_fields=['last_message_at', 'last_sender', 'last_preview'])
    return message


@transaction.atomic
def post_message(conversation, sender, body):
    return _add_message(conversation, sender, body)


@transaction.atomic
def start_private(technician, created_by, subject, body):
    conversation = Conversation.objects.create(
        kind=Conversation.Kind.PRIVATE, technician=technician, subject=subject,
        created_by=created_by, last_message_at=timezone.now(),
    )
    _add_message(conversation, created_by, body)
    return conversation


@transaction.atomic
def send_announcement(created_by, subject, body):
    conversation = Conversation.objects.create(
        kind=Conversation.Kind.ANNOUNCEMENT, subject=subject, created_by=created_by,
        recipient_count=User.objects.filter(role=User.Role.OPERATOR, is_active=True).count(),
        last_message_at=timezone.now(),
    )
    _add_message(conversation, created_by, body)
    return conversation