from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
import re
from accounts.models import User
from customers.models import City, Customer
from jobs.models import Job
from django.test import Client, TestCase
from .models import Notification
from .services import sync_overdue_notifications, unread_count

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