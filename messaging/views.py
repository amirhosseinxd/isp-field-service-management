from collections import Counter

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Max, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import User
from accounts.permissions import role_required
from jobs.views import paginate

from .forms import SUBJECT_MAX, ReplyForm, SupportComposeForm, TechnicianComposeForm
from .models import Conversation, ConversationRead, Message
from .services import (
    badge_text, can_reply, mark_read, newer_support_replies, post_message, recipient_label,
    send_announcement, start_private, unread_count, unread_messages, visible_conversations,
)

ANY_USER = (User.Role.OPERATOR, User.Role.ADMIN)
TABS = [
    ('all', 'همه'), ('unread', 'خوانده‌نشده'), ('unanswered', 'بدون پاسخ'),
    ('announcements', 'اطلاعیه‌ها'), ('private', 'گفت‌وگوها'),
]


@role_required(*ANY_USER)
def inbox(request):
    user = request.user
    is_support = user.role == User.Role.ADMIN
    valid_tabs = [key for key, _ in TABS if is_support or key != 'unanswered']
    tab = request.GET.get('tab', 'all')
    if tab not in valid_tabs:
        tab = 'all'
    q = request.GET.get('q', '').strip() if is_support else ''

    unread_by_conv = Counter(unread_messages(user).values_list('conversation_id', flat=True))
    convs = visible_conversations(user).select_related('technician', 'last_sender')
    if tab == 'unread':
        convs = convs.filter(pk__in=list(unread_by_conv))
    elif tab == 'unanswered':
        convs = convs.filter(kind=Conversation.Kind.PRIVATE, last_sender__role=User.Role.OPERATOR)
    elif tab == 'announcements':
        convs = convs.filter(kind=Conversation.Kind.ANNOUNCEMENT)
    elif tab == 'private':
        convs = convs.filter(kind=Conversation.Kind.PRIVATE)
    for term in q.split():
        convs = convs.filter(
            Q(subject__icontains=term) | Q(technician__first_name__icontains=term)
            | Q(technician__last_name__icontains=term) | Q(technician__username__icontains=term)
        )

    counts = {'unread': len(unread_by_conv)}
    if is_support:
        counts['unanswered'] = Conversation.objects.filter(
            kind=Conversation.Kind.PRIVATE, last_sender__role=User.Role.OPERATOR,
        ).count()
    tabs = [{'key': k, 'label': l, 'count': counts.get(k, 0)} for k, l in TABS if k in valid_tabs]

    page, qs = paginate(request, convs, 20)
    rows = [{'conv': c, 'unread': unread_by_conv.get(c.pk, 0)} for c in page]
    return render(request, 'messaging/inbox.html', {
        'page': page, 'qs': qs, 'rows': rows, 'tabs': tabs, 'tab': tab, 'q': q,
        'unread_total': sum(unread_by_conv.values()),
    })


@role_required(*ANY_USER)
def compose(request):
    user = request.user
    is_support = user.role == User.Role.ADMIN
    if is_support:
        form = SupportComposeForm(request.POST or None, initial={'recipient': request.GET.get('to', '')})
    else:
        initial = {}
        ref = request.GET.get('ref', '')
        if ref.isdigit():
            announcement = Conversation.objects.filter(pk=ref, kind=Conversation.Kind.ANNOUNCEMENT).first()
            if announcement:
                initial['subject'] = f'درباره اطلاعیه: {announcement.subject}'[:SUBJECT_MAX]
        form = TechnicianComposeForm(request.POST or None, initial=initial)

    if request.method == 'POST' and form.is_valid():
        cd = form.cleaned_data
        if not is_support:
            conv = start_private(user, user, cd['subject'], cd['body'])
            messages.success(request, 'پیام شما برای پشتیبانی ارسال شد.')
        elif cd['recipient'] == 'all':
            conv = send_announcement(user, cd['subject'], cd['body'])
            messages.success(request, 'اطلاعیه برای همهٔ تکنسین‌ها ارسال شد.')
        else:
            conv = start_private(form.technicians[cd['recipient']], user, cd['subject'], cd['body'])
            messages.success(request, 'پیام ارسال شد.')
        return redirect('conversation', pk=conv.pk)
    return render(request, 'messaging/compose.html', {'form': form})


@role_required(*ANY_USER)
def conversation(request, pk):
    user = request.user
    is_support = user.role == User.Role.ADMIN
    # Anything the person may not see is a 404, so its existence is not revealed either
    conv = get_object_or_404(
        visible_conversations(user).select_related('technician', 'created_by', 'last_sender'), pk=pk,
    )
    replying = can_reply(user, conv)
    form = ReplyForm(request.POST or None) if replying else None
    highlight_after = None

    if request.method == 'POST':
        if not replying:
            raise PermissionDenied
        if form.is_valid():
            after = request.POST.get('after')
            if is_support and newer_support_replies(conv, user, after):
                highlight_after = int(after)
                form.add_error(
                    None,
                    'پشتیبان دیگری همین الان در این گفت‌وگو پاسخ داده است. پیام‌های جدید را بخوانید '
                    'و در صورت نیاز دوباره ارسال کنید.',
                )
            else:
                post_message(conv, user, form.cleaned_data['body'])
                return redirect('conversation', pk=conv.pk)

    thread = list(conv.messages.select_related('sender'))
    # Computed BEFORE marking as read, so the new messages can be highlighted
    new_ids = set(unread_messages(user).filter(conversation=conv).values_list('id', flat=True))
    if highlight_after is not None:
        new_ids |= {m.id for m in thread if m.id > highlight_after and m.sender_id != user.id}
    for m in thread:
        m.to_label = recipient_label(conv, m)
    last_id = thread[-1].id
    mark_read(user, conv, last_id)

    reader_count = None
    if is_support and conv.kind == Conversation.Kind.ANNOUNCEMENT:
        reader_count = ConversationRead.objects.filter(
            conversation=conv, user__role=User.Role.OPERATOR,
            user__date_joined__lte=conv.created_at, last_read_message_id__gte=thread[0].id,
        ).count()

    return render(request, 'messaging/conversation.html', {
        'conv': conv, 'thread': thread, 'new_ids': new_ids, 'form': form, 'replying': replying,
        'last_id': last_id, 'is_support': is_support, 'reader_count': reader_count,
    })


@role_required(*ANY_USER)
@require_POST
def mark_all_read(request):
    user = request.user
    for conversation_id in set(unread_messages(user).values_list('conversation_id', flat=True)):
        newest = Message.objects.filter(conversation_id=conversation_id).aggregate(m=Max('id'))['m']
        mark_read(user, Conversation.objects.get(pk=conversation_id), newest)
    messages.success(request, 'همهٔ پیام‌ها خوانده‌شده ثبت شد.')
    return redirect('inbox')


@role_required(*ANY_USER)
def unread_json(request):
    count = unread_count(request.user)
    return JsonResponse({'unread': count, 'badge': badge_text(count)})