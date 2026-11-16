import shutil
import tempfile
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from customers.models import City, Customer
from inventory.models import Material

from . import workflows
from .models import Job, JobEvidence, JobMaterialUsage, JobReturn, WorkReport

PASSWORD = 'pass-12345-test'
Cat = JobEvidence.Category
Kind = JobEvidence.Kind


class JobTestBase(TestCase):
    @classmethod
    def setUpClass(cls):
        # Uploaded files go to a throwaway folder, never the real media/ folder
        cls._media_dir = tempfile.mkdtemp(prefix='fsm-test-media-')
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_dir)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media_dir, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username='t_admin', password=PASSWORD, role=User.Role.ADMIN)
        cls.tech = User.objects.create_user(
            username='t_tech', password=PASSWORD, role=User.Role.OPERATOR)
        cls.other_tech = User.objects.create_user(
            username='t_other', password=PASSWORD, role=User.Role.OPERATOR)
        cls.customer = Customer.objects.create(
            subscription_id='0012345678', full_name='مشترک تست', mobile='09120000000',
            address='آدرس تست', city=City.objects.get(name='سمنان'),
            center_number='01', registered_at=timezone.now(),
        )

    def make_job(self, job_type, workflow, operator=None, **fields):
        return Job.objects.create(
            job_type=job_type, workflow=workflow,
            assigned_operator=operator or self.tech,
            created_by=self.admin, customer=self.customer, **fields,
        )

    def add_evidence(self, job, category, kind=Kind.PHOTO, name='x.jpg'):
        return JobEvidence.objects.create(
            job=job, kind=kind, category=category, file=name, uploaded_by=self.tech,
        )

    def use_material(self, job, code, quantity='1', purpose='used'):
        return JobMaterialUsage.objects.create(
            job=job, material=Material.objects.get(code=code),
            quantity=Decimal(quantity), purpose=purpose,
        )

    def missing(self, job):
        return workflows.missing_requirements(job)


class WorkflowRuleTests(JobTestBase):
    def test_invalid_pair_is_rejected_by_database(self):
        # Repair + FTTH inquiry is not allowed
        with self.assertRaises(IntegrityError), transaction.atomic():
            Job.objects.create(
                job_type='repair', workflow='ftth_inquiry',
                assigned_operator=self.tech, created_by=self.admin,
            )

    def test_ftth_feasible_only_needs_description(self):
        job = self.make_job('installation', 'ftth_inquiry', ftth_outcome='feasible')
        missing = self.missing(job)
        self.assertEqual(len(missing), 1)
        self.assertIn('توضیحات', missing[0])

    def test_ftth_unfeasible_needs_video_and_a_photo_does_not_count(self):
        job = self.make_job('installation', 'ftth_inquiry', ftth_outcome='unfeasible')
        self.add_evidence(job, Cat.GENERAL)  # a photo
        self.assertTrue(any('ویدیو' in m for m in self.missing(job)))

        self.add_evidence(job, Cat.VIDEO, kind=Kind.VIDEO, name='x.mp4')
        self.assertFalse(any('ویدیو' in m for m in self.missing(job)))

    def test_fusion_with_splitter_needs_four_photo_steps(self):
        job = self.make_job('installation', 'fusion', fat_needs_splitter=True)
        self.use_material(job, 'M010')  # آداپتور دوبل
        self.use_material(job, 'M012')  # اسپلیتر 16*1
        self.assertEqual(len(self.missing(job)), 5)  # 4 photo steps + description

        for category in (Cat.SPLITTER_BEFORE, Cat.SPLITTER_AFTER, Cat.CASSETTE, Cat.FAT):
            self.add_evidence(job, category)
        self.assertEqual(len(self.missing(job)), 1)  # only the description

    def test_fusion_splitter_must_be_exactly_one_type(self):
        job = self.make_job('installation', 'fusion', fat_needs_splitter=True)
        self.use_material(job, 'M010')
        self.use_material(job, 'M012')
        self.use_material(job, 'M013')  # two splitters
        self.assertTrue(any('دقیقاً یکی' in m or 'حداکثر' in m for m in self.missing(job)))

    def test_fusion_without_splitter_needs_five_photos(self):
        job = self.make_job('installation', 'fusion', fat_needs_splitter=False)
        self.use_material(job, 'M014')  # ATB
        for _ in range(4):
            self.add_evidence(job, Cat.GENERAL)
        self.assertTrue(any('عکس' in m for m in self.missing(job)))  # one still missing

        self.add_evidence(job, Cat.GENERAL)
        self.assertEqual(len(self.missing(job)), 1)  # only the description

    def test_service_delivery_needs_exactly_one_modem(self):
        job = self.make_job(
            'installation', 'service_delivery',
            upload_mbps=Decimal('50'), download_mbps=Decimal('20'),
        )
        for category in (Cat.MOM, Cat.PON_TEST, Cat.SPEED_TEST):
            self.add_evidence(job, category)

        self.assertTrue(any('مودم' in m for m in self.missing(job)))
        self.use_material(job, 'M018')
        self.assertFalse(any('مودم' in m for m in self.missing(job)))
        self.use_material(job, 'M019')  # two modems
        self.assertTrue(any('مودم' in m for m in self.missing(job)))

    def test_tokar_steps_only_apply_when_used(self):
        job = self.make_job('repair', 'drop_cable', tokar_used=False)
        keys = [s.key for s in workflows.applicable_steps(job)]
        self.assertNotIn('متراژ توکار', keys)

        job.tokar_used = True
        keys = [s.key for s in workflows.applicable_steps(job)]
        self.assertIn('متراژ توکار', keys)
        self.assertIn('عکس توکار', keys)

    def test_piece_quantities_must_be_whole_numbers(self):
        job = self.make_job('repair', 'drop_cable')
        with self.assertRaises(ValidationError):
            JobMaterialUsage(job=job, material=Material.objects.get(code='M009'),
                             quantity=Decimal('2.5')).clean()  # قلاب is counted in pieces

        # meters accept decimals, so this must not raise
        JobMaterialUsage(job=job, material=Material.objects.get(code='M005'),
                         quantity=Decimal('2.5')).clean()

    def test_submit_is_refused_while_incomplete_and_leaves_no_report(self):
        job = self.make_job('installation', 'ftth_inquiry', ftth_outcome='unfeasible')
        with self.assertRaises(ValueError):
            job.submit(self.tech, 'desc')
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.ASSIGNED)
        self.assertFalse(WorkReport.objects.filter(job=job).exists())

    def test_submit_succeeds_when_complete(self):
        job = self.make_job('installation', 'ftth_inquiry', ftth_outcome='feasible')
        job.submit(self.tech, 'کار انجام شد')
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.SUBMITTED)
        self.assertIsNotNone(job.submitted_at)
        self.assertEqual(job.report.description, 'کار انجام شد')

    def test_only_assigned_operator_can_submit(self):
        job = self.make_job('installation', 'ftth_inquiry', ftth_outcome='feasible')
        with self.assertRaises(PermissionError):
            job.submit(self.other_tech, 'desc')

    def test_cannot_submit_twice(self):
        job = self.make_job('installation', 'ftth_inquiry', ftth_outcome='feasible')
        job.submit(self.tech, 'desc')
        with self.assertRaises(ValueError):
            job.submit(self.tech, 'desc again')


class ReturnCycleTests(JobTestBase):
    def setUp(self):
        self.job = self.make_job('installation', 'ftth_inquiry', ftth_outcome='feasible')
        self.job.submit(self.tech, 'first description')

    def test_return_needs_a_reason(self):
        with self.assertRaises(ValueError):
            self.job.return_for_correction(self.admin, '   ')

    def test_return_then_resubmit_keeps_history(self):
        self.job.return_for_correction(self.admin, 'عکس ناخوانا است')
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.RETURNED)

        record = JobReturn.objects.get(job=self.job)
        self.assertEqual(record.previous_description, 'first description')
        self.assertIsNone(record.resubmitted_at)

        self.job.submit(self.tech, 'second description')
        self.job.refresh_from_db()
        record.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.SUBMITTED)
        self.assertEqual(self.job.report.description, 'second description')
        self.assertIsNotNone(record.resubmitted_at)

    def test_cannot_return_a_job_that_is_not_submitted(self):
        draft = self.make_job('installation', 'ftth_inquiry', ftth_outcome='feasible')
        with self.assertRaises(ValueError):
            draft.return_for_correction(self.admin, 'reason')

    def test_cannot_return_twice(self):
        self.job.return_for_correction(self.admin, 'first reason')
        with self.assertRaises(ValueError):
            self.job.return_for_correction(self.admin, 'second reason')


class AccessControlTests(JobTestBase):
    def setUp(self):
        self.my_job = self.make_job('installation', 'ftth_inquiry', ftth_outcome='feasible')
        self.their_job = self.make_job(
            'installation', 'ftth_inquiry', operator=self.other_tech, ftth_outcome='feasible',
        )

    def test_operator_cannot_open_support_pages(self):
        self.client.login(username='t_tech', password=PASSWORD)
        for name in ('support_dashboard', 'photo_history', 'customer_list', 'customer_export'):
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_operator_cannot_open_another_technicians_job(self):
        self.client.login(username='t_tech', password=PASSWORD)
        response = self.client.get(reverse('job_start', args=[self.their_job.pk]))
        self.assertEqual(response.status_code, 404)

    def test_anonymous_user_is_sent_to_login_for_photos(self):
        photo = self.add_evidence(self.my_job, Cat.GENERAL)
        response = self.client.get(reverse('photo_file', args=[photo.pk]))
        self.assertEqual(response.status_code, 302)

    def test_other_technician_cannot_view_a_photo(self):
        photo = self.add_evidence(self.my_job, Cat.GENERAL)
        self.client.login(username='t_other', password=PASSWORD)
        response = self.client.get(reverse('photo_file', args=[photo.pk]))
        self.assertEqual(response.status_code, 404)

    def test_owner_can_open_own_photo(self):
        photo = JobEvidence.objects.create(
            job=self.my_job, kind=Kind.PHOTO, category=Cat.GENERAL,
            file=SimpleUploadedFile('p.jpg', b'\xff\xd8\xff\xe0test', content_type='image/jpeg'),
            uploaded_by=self.tech,
        )
        self.client.login(username='t_tech', password=PASSWORD)
        response = self.client.get(reverse('photo_file', args=[photo.pk]))
        self.assertEqual(response.status_code, 200)

    def test_video_url_refuses_a_photo(self):
        photo = self.add_evidence(self.my_job, Cat.GENERAL)
        self.client.login(username='t_tech', password=PASSWORD)
        response = self.client.get(reverse('video_file', args=[photo.pk]))
        self.assertEqual(response.status_code, 404)

    def test_technician_cannot_delete_evidence_after_submit(self):
        self.my_job.submit(self.tech, 'desc')
        photo = self.add_evidence(self.my_job, Cat.GENERAL)
        self.client.login(username='t_tech', password=PASSWORD)
        self.client.post(reverse('job_evidence_delete', args=[self.my_job.pk, 0, photo.pk]))
        self.assertTrue(JobEvidence.objects.filter(pk=photo.pk).exists())