from django.test import TestCase
from django.urls import reverse

from accounts.models import User

from .models import Conversation
from .services import post_message, send_announcement, start_private, unread_count

PASSWORD = 'Pass-12345-xyz'


def make_user(username, role=User.Role.OPERATOR, **extra):
    return User.objects.create_user(
        username=username, password=PASSWORD, role=role,
        first_name=extra.pop('first_name', username), last_name='تست', **extra,
    )


class Base(TestCase):
    def setUp(self):
        self.sara = make_user('sara', User.Role.ADMIN, first_name='سارا')
        self.omid = make_user('omid', User.Role.ADMIN, first_name='امید')
        self.ali = make_user('ali', first_name='علی')
        self.reza = make_user('reza', first_name='رضا')

    def login(self, user):
        self.assertTrue(self.client.login(username=user.username, password=PASSWORD))


class VisibilityTests(Base):
    def test_technicians_only_see_their_own_private_conversations_and_announcements(self):
        mine = start_private(self.ali, self.ali, 'Subject-Mine', 'سلام')
        theirs = start_private(self.reza, self.reza, 'Subject-Reza', 'سلام')
        news = send_announcement(self.sara, 'Subject-News', 'متن')
        self.login(self.ali)
        self.assertEqual(self.client.get(reverse('conversation', args=[mine.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('conversation', args=[news.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('conversation', args=[theirs.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('conversation', args=[theirs.pk]), {'body': 'x'}).status_code, 404)
        listing = self.client.get(reverse('inbox'))
        self.assertContains(listing, 'Subject-Mine')
        self.assertNotContains(listing, 'Subject-Reza')

    def test_every_support_sees_the_shared_inbox(self):
        start_private(self.ali, self.ali, 'Subject-Ali', 'سلام')
        start_private(self.reza, self.reza, 'Subject-Reza', 'سلام')
        for support in (self.sara, self.omid):
            self.login(support)
            listing = self.client.get(reverse('inbox'))
            self.assertContains(listing, 'Subject-Ali')
            self.assertContains(listing, 'Subject-Reza')

    def test_anonymous_visitors_are_sent_to_login(self):
        self.assertEqual(self.client.get(reverse('inbox')).status_code, 302)


class ConversationFlowTests(Base):
    def test_technician_message_reaches_support_and_replies_show_who_answered(self):
        self.login(self.ali)
        self.client.post(reverse('message_new'), {'subject': 'مشکل مودم', 'body': 'کمک'})
        conv = Conversation.objects.get(subject='مشکل مودم')
        self.assertEqual(conv.technician, self.ali)
        self.assertEqual(conv.kind, Conversation.Kind.PRIVATE)

        self.login(self.sara)
        url = reverse('conversation', args=[conv.pk])
        self.assertContains(self.client.get(url), 'کمک')
        self.client.post(url, {'body': 'در حال بررسی', 'after': conv.messages.last().pk})
        self.assertEqual(conv.messages.count(), 2)
        self.assertEqual(conv.messages.last().sender, self.sara)

        self.login(self.omid)
        page = self.client.get(url)
        self.assertContains(page, 'سارا')                  # the other support sees who answered
        self.assertContains(page, 'قبلاً پاسخ داده')

        self.login(self.ali)
        self.assertContains(self.client.get(url), 'سارا')   # the technician sees the replying support's name

    def test_a_second_support_is_warned_instead_of_sending_a_duplicate_reply(self):
        conv = start_private(self.ali, self.ali, 'سوال', 'سلام')
        url = reverse('conversation', args=[conv.pk])
        seen = conv.messages.last().pk                      # both supports loaded the page at this point
        self.login(self.sara)
        self.client.post(url, {'body': 'پاسخ سارا', 'after': seen})
        self.login(self.omid)
        response = self.client.post(url, {'body': 'پاسخ امید', 'after': seen})
        self.assertEqual(response.status_code, 200)         # shown again with a warning
        self.assertEqual(conv.messages.count(), 2)
        self.assertContains(response, 'پاسخ امید')           # his text is still in the box
        self.client.post(url, {'body': 'پاسخ امید', 'after': conv.messages.last().pk})
        self.assertEqual(conv.messages.count(), 3)


class AnnouncementTests(Base):
    def test_announcement_reaches_every_technician_but_nobody_can_reply_in_it(self):
        self.login(self.sara)
        self.client.post(reverse('message_new'), {'recipient': 'all', 'subject': 'تعطیلی', 'body': 'فردا تعطیل است'})
        conv = Conversation.objects.get(subject='تعطیلی')
        self.assertEqual(conv.kind, Conversation.Kind.ANNOUNCEMENT)
        self.assertEqual(conv.recipient_count, 2)
        url = reverse('conversation', args=[conv.pk])
        for person in (self.ali, self.reza, self.omid):
            self.login(person)
            self.assertContains(self.client.get(reverse('inbox')), 'تعطیلی')
            self.assertEqual(self.client.post(url, {'body': 'x'}).status_code, 403)
        self.assertEqual(conv.messages.count(), 1)

    def test_private_message_to_one_technician_is_hidden_from_the_others(self):
        self.login(self.sara)
        self.client.post(reverse('message_new'), {
            'recipient': str(self.ali.pk), 'subject': 'Private-Subject-1', 'body': 'فقط برای علی',
        })
        conv = Conversation.objects.get(subject='Private-Subject-1')
        self.assertEqual(conv.technician, self.ali)
        self.login(self.reza)
        self.assertEqual(self.client.get(reverse('conversation', args=[conv.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse('inbox')), 'Private-Subject-1')

    def test_support_can_only_pick_active_technicians(self):
        gone = make_user('gone', is_active=False)
        self.login(self.sara)
        self.assertNotContains(self.client.get(reverse('message_new')), 'gone')
        response = self.client.post(reverse('message_new'), {'recipient': str(gone.pk), 'subject': 's', 'body': 'b'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Conversation.objects.exists())


class UnreadTests(Base):
    def test_technician_unread_counts_and_automatic_mark_as_read(self):
        conv = start_private(self.ali, self.sara, 'سوال', 'پیام اول')
        post_message(conv, self.sara, 'پیام دوم')
        self.assertEqual(unread_count(self.ali), 2)
        self.assertEqual(unread_count(self.reza), 0)
        self.login(self.ali)
        self.assertEqual(self.client.get(reverse('messages_unread')).json()['unread'], 2)
        self.assertContains(self.client.get(reverse('inbox')), '<span class="mail-badge">')
        self.client.get(reverse('conversation', args=[conv.pk]))
        self.assertEqual(unread_count(self.ali), 0)
        self.assertContains(self.client.get(reverse('inbox')), '<span class="mail-badge" hidden>')
        post_message(conv, self.sara, 'پیام سوم')
        self.assertEqual(unread_count(self.ali), 1)

    def test_support_unread_is_personal_and_counts_technician_messages(self):
        conv = start_private(self.ali, self.ali, 'مشکل', 'سلام')
        self.assertEqual(unread_count(self.sara), 1)
        self.assertEqual(unread_count(self.omid), 1)
        self.login(self.sara)
        self.client.get(reverse('conversation', args=[conv.pk]))
        self.assertEqual(unread_count(self.sara), 0)
        self.assertEqual(unread_count(self.omid), 1)         # his own indicator stays until he opens it
        post_message(conv, self.sara, 'پاسخ')
        self.assertEqual(unread_count(self.omid), 1)         # another support's reply is not "unread"
        self.assertEqual(unread_count(self.ali), 1)

    def test_old_announcements_are_not_unread_for_a_new_technician(self):
        send_announcement(self.sara, 'قدیمی', 'متن')
        newcomer = make_user('newcomer')
        self.assertEqual(unread_count(newcomer), 0)
        send_announcement(self.sara, 'جدید', 'متن')
        self.assertEqual(unread_count(newcomer), 1)
        self.assertEqual(unread_count(self.ali), 2)
        self.assertEqual(unread_count(self.sara), 0)         # support is not notified about announcements

    def test_mark_all_read(self):
        start_private(self.ali, self.sara, 'یک', 'سلام')
        send_announcement(self.sara, 'دو', 'سلام')
        self.login(self.ali)
        self.client.post(reverse('messages_read_all'))
        self.assertEqual(unread_count(self.ali), 0)

    def test_the_badge_poll_does_not_count_as_activity(self):
        self.login(self.ali)
        self.client.get(reverse('messages_unread'))
        self.assertIsNone(User.objects.get(pk=self.ali.pk).last_seen)


class HistoryTests(Base):
    def test_messages_cannot_be_edited_or_deleted(self):
        message = start_private(self.ali, self.ali, 'x', 'y').messages.get()
        with self.assertRaises(PermissionError):
            message.delete()
        message.body = 'changed'
        with self.assertRaises(PermissionError):
            message.save()