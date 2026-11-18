from datetime import timedelta
from django.test import TestCase
from django.urls import reverse
import re
from accounts.models import User
from customers.models import City, Customer
from jobs.models import Job
from .models import Notification
from .services import sync_overdue_notifications, unread_count


import json
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from pywebpush import WebPushException


from .models import Notification, PushSubscription


PASSWORD = 'pw-12345-test'


def make_customer(number, days_ago):
    return Customer.objects.create(
        subscription_id=number, full_name=f'مشترک {number}', mobile='09120000000',
        address='آدرس', city=City.objects.get(name='سمنان'), center_number='01',
        registered_at=timezone.now() - timedelta(days=days_ago),
    )


class NotificationTests(TestCase):
    def setUp(self):
        cache.clear()  # the page-visit check is throttled through the cache
        make = User.objects.create_user
        self.admin = make(username='n_admin', password=PASSWORD, role=User.Role.ADMIN)
        self.admin2 = make(username='n_admin2', password=PASSWORD, role=User.Role.ADMIN)
        self.tech = make(username='n_tech', password=PASSWORD, role=User.Role.OPERATOR)
        self.tech2 = make(username='n_tech2', password=PASSWORD, role=User.Role.OPERATOR)
        self.new_customer = make_customer('0000000001', days_ago=5)
        self.old_customer = make_customer('0000000002', days_ago=20)

    def make_job(self, customer=None, operator=None):
        return Job.objects.create(
            job_type='installation', workflow='fusion',
            assigned_operator=operator or self.tech, created_by=self.admin,
            customer=customer or self.new_customer,
        )

    # --- technician notices ---

    def test_new_job_notifies_only_the_assigned_technician(self):
        job = self.make_job()
        self.assertEqual(
            Notification.objects.filter(kind='job_assigned', job=job, recipient=self.tech).count(), 1,
        )
        self.assertFalse(Notification.objects.exclude(recipient=self.tech).exists())

    def test_later_saves_do_not_create_duplicates(self):
        job = self.make_job()
        job.status = Job.Status.IN_PROGRESS
        job.save(update_fields=['status'])
        job.save()
        self.assertEqual(Notification.objects.filter(job=job, kind='job_assigned').count(), 1)

    def test_reassigning_notifies_the_new_technician_and_retires_the_old_notice(self):
        job = Job.objects.get(pk=self.make_job().pk)  # loaded from the database, as the admin would
        job.assigned_operator = self.tech2
        job.save()
        self.assertTrue(
            Notification.objects.filter(recipient=self.tech2, job=job, resolved_at__isnull=True).exists()
        )
        self.assertIsNotNone(Notification.objects.get(recipient=self.tech, job=job).resolved_at)

    # --- support notices ---

    def test_overdue_creates_one_notice_per_admin_and_never_duplicates(self):
        job = self.make_job(customer=self.old_customer)
        sync_overdue_notifications()
        sync_overdue_notifications()
        notices = Notification.objects.filter(kind='job_overdue', job=job)
        self.assertEqual(notices.count(), 2)
        self.assertEqual(
            set(notices.values_list('recipient', flat=True)), {self.admin.pk, self.admin2.pk},
        )
        self.assertFalse(Notification.objects.filter(kind='job_overdue', recipient=self.tech).exists())

    def test_recent_customer_is_not_overdue(self):
        self.make_job(customer=self.new_customer)
        sync_overdue_notifications()
        self.assertFalse(Notification.objects.filter(kind='job_overdue').exists())

    def test_reviewed_job_retires_the_notice_and_keeps_its_read_state(self):
        job = self.make_job(customer=self.old_customer)
        sync_overdue_notifications()
        notice = Notification.objects.get(kind='job_overdue', job=job, recipient=self.admin)
        Notification.objects.filter(pk=notice.pk).update(read_at=timezone.now())

        Job.objects.filter(pk=job.pk).update(status=Job.Status.REVIEWED)
        sync_overdue_notifications()

        notice.refresh_from_db()
        self.assertIsNotNone(notice.resolved_at)
        self.assertIsNotNone(notice.read_at)            # the read state is preserved
        self.assertEqual(unread_count(self.admin2), 0)  # a retired notice no longer counts

    def test_visiting_a_page_as_admin_creates_overdue_notices(self):
        job = self.make_job(customer=self.old_customer)
        self.client.login(username='n_admin', password=PASSWORD)
        self.client.get(reverse('support_dashboard'))
        self.assertTrue(
            Notification.objects.filter(kind='job_overdue', job=job, recipient=self.admin).exists()
        )

    # --- the bell ---

    def test_bell_with_badge_is_in_the_page(self):
        self.make_job()
        self.client.login(username='n_tech', password=PASSWORD)
        response = self.client.get(reverse('operator_home'))
        self.assertContains(response, 'id="bell"')
        self.assertContains(response, 'کار جدید به شما ارجاع شد')
        self.assertContains(response, 'class="bell-badge">۱<')

    def test_a_user_cannot_open_or_mark_someone_elses_notice(self):
        notice = Notification.objects.get(recipient=self.tech, job=self.make_job())
        self.client.login(username='n_tech2', password=PASSWORD)
        self.assertEqual(
            self.client.get(reverse('notification_open', args=[notice.pk])).status_code, 404,
        )
        self.client.post(reverse('notification_read', args=[notice.pk]))
        notice.refresh_from_db()
        self.assertIsNone(notice.read_at)

    def test_opening_a_notice_marks_it_read_and_goes_to_the_job(self):
        job = self.make_job()
        notice = Notification.objects.get(recipient=self.tech, job=job)
        self.client.login(username='n_tech', password=PASSWORD)
        response = self.client.get(reverse('notification_open', args=[notice.pk]))
        self.assertRedirects(
            response, reverse('job_start', args=[job.pk]), fetch_redirect_response=False,
        )
        notice.refresh_from_db()
        self.assertIsNotNone(notice.read_at)

    def test_mark_one_and_mark_all_as_read(self):
        self.make_job()
        self.make_job()
        self.client.login(username='n_tech', password=PASSWORD)
        first = Notification.objects.filter(recipient=self.tech).first()
        data = self.client.post(reverse('notification_read', args=[first.pk])).json()
        self.assertEqual(data['unread'], 1)
        data = self.client.post(reverse('notification_read_all')).json()
        self.assertEqual(data['unread'], 0)

    def test_notifications_survive_logout_and_login(self):
        self.make_job()
        self.client.login(username='n_tech', password=PASSWORD)
        self.client.logout()
        self.client.login(username='n_tech', password=PASSWORD)
        self.assertEqual(self.client.get(reverse('notification_panel')).json()['unread'], 1)

    def test_anonymous_users_are_sent_to_login(self):
        self.assertEqual(self.client.get(reverse('notification_panel')).status_code, 302)







    def test_bell_carries_its_own_csrf_token(self):
        self.make_job()
        self.client.login(username='n_tech', password=PASSWORD)
        response = self.client.get(reverse('operator_home'))
        self.assertContains(response, 'data-csrf="')
        self.assertNotContains(response, 'data-csrf="NOTPROVIDED"')

    def test_marking_read_works_when_csrf_is_enforced(self):
        self.make_job()
        client = Client(enforce_csrf_checks=True)  # the normal test client skips the CSRF check
        client.login(username='n_tech', password=PASSWORD)
        page = client.get(reverse('operator_home'))
        token = re.search(r'data-csrf="([^"]+)"', page.content.decode()).group(1)
        response = client.post(reverse('notification_read_all'), HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['unread'], 0)









class PushTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # A throwaway key, so tests never touch your real vapid_private.pem
        cls._dir = tempfile.mkdtemp(prefix='fsm-vapid-')
        cls._key_path = Path(cls._dir) / 'vapid.pem'
        key = ec.generate_private_key(ec.SECP256R1())
        cls._key_path.write_bytes(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        cls._override = override_settings(
            VAPID_PRIVATE_KEY_FILE=cls._key_path, VAPID_ADMIN_SUBJECT='mailto:test@example.com',
        )
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._dir, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        cache.clear()
        make = User.objects.create_user
        self.admin = make(username='p_admin', password=PASSWORD, role=User.Role.ADMIN)
        self.tech = make(username='p_tech', password=PASSWORD, role=User.Role.OPERATOR)
        self.tech2 = make(username='p_tech2', password=PASSWORD, role=User.Role.OPERATOR)
        self.new_customer = make_customer('0000000001', days_ago=5)
        self.old_customer = make_customer('0000000002', days_ago=20)

    def make_job(self, customer=None, operator=None):
        return Job.objects.create(
            job_type='installation', workflow='fusion',
            assigned_operator=operator or self.tech, created_by=self.admin,
            customer=customer or self.new_customer,
        )

    def subscribe(self, user, name):
        return PushSubscription.objects.create(
            user=user, endpoint=f'https://fcm.googleapis.com/fcm/send/{name}', p256dh='k', auth='a',
        )

    def post_json(self, client, name, data):
        return client.post(reverse(name), data=json.dumps(data), content_type='application/json')

    # --- what gets sent, and to whom ---

    def test_assignment_pushes_only_to_the_assigned_technician(self):
        self.subscribe(self.tech, 'tech')
        self.subscribe(self.tech2, 'tech2')
        with mock.patch('notifications.push.webpush') as sender, \
                self.captureOnCommitCallbacks(execute=True):
            job = self.make_job()
        self.assertEqual(sender.call_count, 1)
        kwargs = sender.call_args.kwargs
        self.assertTrue(kwargs['subscription_info']['endpoint'].endswith('/tech'))
        payload = json.loads(kwargs['data'])
        self.assertEqual(payload['title'], 'کار جدید به شما ارجاع شد')
        notice = Notification.objects.get(recipient=self.tech, job=job)
        self.assertEqual(payload['url'], reverse('notification_open', args=[notice.pk]))

    def test_expired_subscription_is_removed(self):
        self.subscribe(self.tech, 'gone')
        gone = WebPushException('gone', response=SimpleNamespace(status_code=410))
        with mock.patch('notifications.push.webpush', side_effect=gone), \
                self.captureOnCommitCallbacks(execute=True):
            self.make_job()
        self.assertFalse(PushSubscription.objects.filter(endpoint__endswith='/gone').exists())

    def test_a_failing_push_never_breaks_the_app(self):
        self.subscribe(self.tech, 'flaky')
        with mock.patch('notifications.push.webpush', side_effect=RuntimeError('boom')), \
                self.assertLogs('notifications.push', level='ERROR'), \
                self.captureOnCommitCallbacks(execute=True):
            job = self.make_job()
        self.assertTrue(Job.objects.filter(pk=job.pk).exists())
        self.assertTrue(PushSubscription.objects.filter(endpoint__endswith='/flaky').exists())

    def test_nothing_is_sent_when_push_is_not_set_up(self):
        self.subscribe(self.tech, 'tech')
        missing = Path(self._dir) / 'missing.pem'
        with override_settings(VAPID_PRIVATE_KEY_FILE=missing), \
                mock.patch('notifications.push.webpush') as sender, \
                self.captureOnCommitCallbacks(execute=True):
            self.make_job()
        sender.assert_not_called()

    def test_several_new_overdue_notices_become_one_summary_push(self):
        self.subscribe(self.admin, 'admin')
        for _ in range(3):
            self.make_job(customer=self.old_customer)
        with mock.patch('notifications.push.webpush') as sender, \
                self.captureOnCommitCallbacks(execute=True):
            sync_overdue_notifications()
        self.assertEqual(sender.call_count, 1)
        self.assertEqual(json.loads(sender.call_args.kwargs['data'])['title'], 'کارهای معوق جدید')

        # Running the check again finds nothing new, so nothing is pushed
        with mock.patch('notifications.push.webpush') as sender, \
                self.captureOnCommitCallbacks(execute=True):
            sync_overdue_notifications()
        sender.assert_not_called()

    def test_one_new_overdue_notice_is_pushed_with_its_details(self):
        self.subscribe(self.admin, 'admin')
        self.make_job(customer=self.old_customer)
        with mock.patch('notifications.push.webpush') as sender, \
                self.captureOnCommitCallbacks(execute=True):
            sync_overdue_notifications()
        payload = json.loads(sender.call_args.kwargs['data'])
        self.assertIn(self.old_customer.full_name, payload['title'])

    # --- subscribing from the browser ---

    def test_subscribe_stores_the_device_and_moves_it_to_whoever_logs_in_next(self):
        device = {'endpoint': 'https://fcm.googleapis.com/fcm/send/shared',
                  'keys': {'p256dh': 'k', 'auth': 'a'}}
        first, second = Client(), Client()
        first.login(username='p_tech', password=PASSWORD)
        second.login(username='p_tech2', password=PASSWORD)
        self.assertEqual(self.post_json(first, 'push_subscribe', device).status_code, 200)
        self.assertEqual(PushSubscription.objects.get().user, self.tech)
        self.post_json(second, 'push_subscribe', device)      # the same browser, a new login
        row = PushSubscription.objects.get()
        self.assertEqual(row.user, self.tech2)

    def test_subscribe_refuses_unknown_addresses_and_bad_data(self):
        self.client.login(username='p_tech', password=PASSWORD)
        bad_host = {'endpoint': 'https://internal.example/x', 'keys': {'p256dh': 'k', 'auth': 'a'}}
        self.assertEqual(self.post_json(self.client, 'push_subscribe', bad_host).status_code, 400)
        self.assertEqual(self.post_json(self.client, 'push_subscribe', {'endpoint': 'x'}).status_code, 400)
        self.assertFalse(PushSubscription.objects.exists())

    def test_unsubscribe_only_removes_your_own_device(self):
        mine = self.subscribe(self.tech, 'mine')
        theirs = self.subscribe(self.tech2, 'theirs')
        self.client.login(username='p_tech', password=PASSWORD)
        self.post_json(self.client, 'push_unsubscribe', {'endpoint': theirs.endpoint})
        self.assertTrue(PushSubscription.objects.filter(pk=theirs.pk).exists())
        self.post_json(self.client, 'push_unsubscribe', {'endpoint': mine.endpoint})
        self.assertFalse(PushSubscription.objects.filter(pk=mine.pk).exists())

    def test_logging_out_removes_that_devices_subscription(self):
        device = {'endpoint': 'https://fcm.googleapis.com/fcm/send/logout',
                  'keys': {'p256dh': 'k', 'auth': 'a'}}
        self.client.login(username='p_tech', password=PASSWORD)
        self.post_json(self.client, 'push_subscribe', device)
        self.assertEqual(PushSubscription.objects.count(), 1)
        self.client.post(reverse('logout'))
        self.assertEqual(PushSubscription.objects.count(), 0)

    def test_the_background_script_is_served_from_the_site_root(self):
        response = self.client.get('/sw.js')
        self.assertEqual(response.status_code, 200)
        self.assertIn('javascript', response['Content-Type'])
        self.assertContains(response, "addEventListener('push'")

    def test_the_enable_control_gets_the_public_key(self):
        self.client.login(username='p_tech', password=PASSWORD)
        page = self.client.get(reverse('operator_home')).content.decode()
        key = re.search(r'data-vapid-key="([^"]*)"', page).group(1)
        self.assertGreater(len(key), 60)   # a real key, not an empty string