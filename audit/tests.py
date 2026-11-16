from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from jobs.models import Job

from .models import AuditEntry

PASSWORD = 'pw-12345-test'


class AuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username='a_admin', password=PASSWORD, role=User.Role.ADMIN)
        cls.tech = User.objects.create_user(
            username='a_tech', password=PASSWORD, role=User.Role.OPERATOR)

    def make_job(self, **fields):
        return Job.objects.create(
            job_type='installation', workflow='ftth_inquiry',
            assigned_operator=self.tech, created_by=self.admin,
            ftth_outcome=fields.pop('ftth_outcome', 'feasible'), **fields,
        )

    def test_submit_return_resubmit_review_are_logged_in_order(self):
        job = self.make_job()
        job.submit(self.tech, 'desc')
        job.return_for_correction(self.admin, 'unclear photo')
        job.submit(self.tech, 'fixed')
        job.mark_reviewed(self.admin)
        actions = list(
            AuditEntry.objects.filter(target_type='job', target_id=job.pk)
            .order_by('id').values_list('action', flat=True)
        )
        self.assertEqual(
            actions, ['job_submitted', 'job_returned', 'job_submitted', 'job_reviewed'],
        )

    def test_failed_submit_leaves_no_entry(self):
        job = self.make_job(ftth_outcome='unfeasible')  # needs a video it doesn't have
        with self.assertRaises(ValueError):
            job.submit(self.tech, 'desc')
        self.assertFalse(AuditEntry.objects.filter(target_id=job.pk).exists())

    def test_entries_cannot_be_changed_or_deleted(self):
        entry = AuditEntry.objects.create(action='login', actor_username='x')
        entry.details = 'changed'
        with self.assertRaises(PermissionError):
            entry.save()
        with self.assertRaises(PermissionError):
            entry.delete()

    def test_login_is_logged(self):
        self.client.login(username='a_tech', password=PASSWORD)
        self.assertTrue(AuditEntry.objects.filter(action='login', actor=self.tech).exists())

    def test_failed_login_records_username_but_not_password(self):
        self.client.post(reverse('login'), {'username': 'a_tech', 'password': 'wrong-pass-999'})
        entry = AuditEntry.objects.get(action='login_failed')
        self.assertEqual(entry.actor_username, 'a_tech')
        self.assertNotIn('wrong-pass-999', entry.actor_username + entry.details)

    def test_only_admins_can_open_the_log(self):
        self.client.login(username='a_tech', password=PASSWORD)
        self.assertEqual(self.client.get(reverse('audit_list')).status_code, 403)
        self.client.logout()
        self.client.login(username='a_admin', password=PASSWORD)
        self.assertEqual(self.client.get(reverse('audit_list')).status_code, 200)