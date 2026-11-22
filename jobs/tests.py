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
from notifications.models import Notification
from accounts.models import User
from customers.models import City, Customer
from inventory.models import Material

from . import workflows
from .models import Job, JobEvidence, JobMaterialUsage, JobReturn, WorkReport

PASSWORD = 'pass-12345-test'
Cat = JobEvidence.Category
Kind = JobEvidence.Kind


import io
from datetime import timedelta

import jdatetime
from openpyxl import load_workbook

from accounts.templatetags.jalali_tags import jalali

from .reports import DETAIL_SHEET, SUMMARY_SHEET, collect_report, format_duration


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
        # A malfunction repair job can't use the fusion workflow
        with self.assertRaises(IntegrityError), transaction.atomic():
            Job.objects.create(
                job_type='malfunction_repair', workflow='fusion',
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

    def test_fusion_with_splitter_needs_receipt_and_four_photo_steps(self):
        job = self.make_job('installation', 'fusion', fat_needs_splitter=True)
        self.use_material(job, 'M010')  # آداپتور دوبل
        self.use_material(job, 'M012')  # اسپلیتر 16*1
        self.assertEqual(len(self.missing(job)), 6)  # receipt + 4 photo steps + description

        for category in (Cat.RECEIPT, Cat.SPLITTER_BEFORE, Cat.SPLITTER_AFTER, Cat.CASSETTE, Cat.FAT):
            self.add_evidence(job, category)
        self.assertEqual(len(self.missing(job)), 1)  # only the description


    def test_fusion_splitter_must_be_exactly_one_type(self):
        job = self.make_job('installation', 'fusion', fat_needs_splitter=True)
        self.use_material(job, 'M010')
        self.use_material(job, 'M012')
        self.use_material(job, 'M013')  # two splitters
        self.assertTrue(any('دقیقاً یکی' in m or 'حداکثر' in m for m in self.missing(job)))

    def test_fusion_without_splitter_needs_receipt_and_five_photos(self):
        job = self.make_job('installation', 'fusion', fat_needs_splitter=False)
        self.use_material(job, 'M014')  # ATB
        self.add_evidence(job, Cat.RECEIPT)
        for _ in range(4):
            self.add_evidence(job, Cat.GENERAL)
        self.assertTrue(any('عکس' in m for m in self.missing(job)))  # one photo still missing

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
        job = self.make_job('installation', 'drop_cable', tokar_used=False)
        keys = [s.key for s in workflows.applicable_steps(job)]
        self.assertNotIn('متراژ توکار', keys)

        job.tokar_used = True
        keys = [s.key for s in workflows.applicable_steps(job)]
        self.assertIn('متراژ توکار', keys)
        self.assertIn('عکس توکار', keys)

    def test_piece_quantities_must_be_whole_numbers(self):
        job = self.make_job('installation', 'drop_cable')
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
    def test_receipt_is_a_fusion_step_right_after_location_not_a_drop_cable_step(self):
        drop = [s.key for s in workflows.applicable_steps(
            self.make_job('installation', 'drop_cable', tokar_used=False))]
        fusion = [s.key for s in workflows.applicable_steps(self.make_job('installation', 'fusion'))]
        self.assertNotIn('عکس رسید', drop)
        self.assertEqual(fusion[0], 'عکس رسید')

    def test_ftth_needs_materials_needs_only_one_photo(self):
        job = self.make_job('installation', 'ftth_inquiry', ftth_outcome='needs_materials')
        self.assertTrue(any('عکس' in m for m in self.missing(job)))
        self.add_evidence(job, Cat.GENERAL)
        self.assertFalse(any('عکس' in m for m in self.missing(job)))

    def test_materials_were_renamed_and_nothing_else_changed(self):
        names = dict(Material.objects.filter(code__in=['M001', 'M004', 'M016']).values_list('code', 'name'))
        self.assertEqual(names, {'M001': 'دراپ 2کر', 'M004': 'مینی', 'M016': 'پچکورد'})
        self.assertEqual(Material.objects.get(code='M001').unit, 'متر')
        self.assertEqual(Material.objects.count(), 19)


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








class TechnicianPanelTests(JobTestBase):
    def test_home_shows_workflow_customer_and_relative_time(self):
        self.make_job('installation', 'fusion')
        self.client.login(username='t_tech', password=PASSWORD)
        response = self.client.get(reverse('operator_home'))
        self.assertContains(response, 'فیوژن')        # the workflow
        self.assertContains(response, 'مشترک تست')    # the customer
        self.assertContains(response, 'پیش')          # relative time wording

    def test_job_page_has_back_link_info_box_and_tap_to_call(self):
        job = self.make_job('installation', 'fusion')
        self.client.login(username='t_tech', password=PASSWORD)
        response = self.client.get(reverse('job_location', args=[job.pk]))
        self.assertContains(response, f'href="{reverse("operator_home")}"')
        self.assertContains(response, 'href="tel:09120000000"')
        self.assertContains(response, 'سمنان')



    def test_materials_screen_marks_saved_rows_as_selected(self):
        job = self.make_job(
            'installation', 'ftth_inquiry', ftth_outcome='needs_materials',
            latitude=Decimal('35.1'), longitude=Decimal('51.1'),
        )
        self.add_evidence(job, Cat.GENERAL)
        self.add_evidence(job, Cat.GENERAL)
        self.use_material(job, 'M003', '10.5', purpose='needed')

        self.client.login(username='t_tech', password=PASSWORD)
        response = self.client.get(reverse('job_step', args=[job.pk, 2]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="mat-row is-selected"')  # the saved one
        self.assertContains(response, 'class="mat-row"')              # the unselected ones



    def test_submitted_jobs_show_when_they_were_submitted(self):
        job = self.make_job('installation', 'fusion', status=Job.Status.SUBMITTED)
        Job.objects.filter(pk=job.pk).update(submitted_at=timezone.now() - timedelta(minutes=5))
        self.client.login(username='t_tech', password=PASSWORD)
        self.assertContains(self.client.get(reverse('operator_home')), 'ارسال: ۵ دقیقه پیش')








class TechnicianReportTests(JobTestBase):
    def job(self, operator, hours_to_submit=None, status=Job.Status.ASSIGNED,
            returned=False, days_ago=2):
        job = self.make_job('installation', 'fusion', operator=operator)
        created = timezone.now() - timedelta(days=days_ago)
        fields = {'created_at': created, 'status': status}
        if hours_to_submit is not None:
            fields['submitted_at'] = created + timedelta(hours=hours_to_submit)
        Job.objects.filter(pk=job.pk).update(**fields)
        if returned:
            JobReturn.objects.create(job=job, reason='x', returned_by=self.admin)
        job.refresh_from_db()
        return job

    def row_for(self, report, name):
        return next(r for r in report['summary'] if r['name'] == name)

    def test_summary_numbers_and_average(self):
        self.job(self.tech, 2, Job.Status.SUBMITTED)
        self.job(self.tech, 4, Job.Status.REVIEWED)
        self.job(self.tech, 6, Job.Status.RETURNED, returned=True)
        self.job(self.tech)  # never submitted
        row = self.row_for(collect_report(), 't_tech')
        self.assertEqual(row['total'], 4)
        self.assertEqual(row['completed'], 3)
        self.assertEqual(row['approved'], 1)
        self.assertEqual(row['returned'], 1)
        self.assertEqual(row['in_progress'], 1)
        self.assertEqual(row['average'], timedelta(hours=4))   # (2 + 4 + 6) / 3

    def test_technicians_do_not_mix_and_idle_ones_still_appear(self):
        self.job(self.tech, 2, Job.Status.SUBMITTED)
        report = collect_report()
        idle = self.row_for(report, 't_other')
        self.assertEqual((idle['total'], idle['completed'], idle['in_progress']), (0, 0, 0))
        self.assertIsNone(idle['average'])

    def test_period_applies_to_both_sheets(self):
        self.job(self.tech, 2, Job.Status.SUBMITTED, days_ago=2)
        self.job(self.tech, 2, Job.Status.SUBMITTED, days_ago=40)
        since = timezone.localdate() - timedelta(days=10)
        report = collect_report(date_from=since)
        self.assertEqual(self.row_for(report, 't_tech')['total'], 1)
        self.assertEqual(len(report['details']), 1)

    def test_detail_row_shows_used_materials_and_time_taken(self):
        job = self.job(self.tech, 2, Job.Status.SUBMITTED)
        self.use_material(job, 'M005', '12.5')                    # used
        self.use_material(job, 'M003', '5', purpose='needed')     # only needed: not listed
        detail = collect_report()['details'][0]
        self.assertIn('12.5', detail['materials'])
        self.assertNotIn('دراپ 4 کر', detail['materials'])
        self.assertEqual(detail['duration'], timedelta(hours=2))
        self.assertEqual(detail['customer'], 'مشترک تست')

    def test_duration_text(self):
        RLM = '\u200f'

        self.assertEqual(
        format_duration(timedelta(days=2, hours=3)),
        f'{RLM}2 روز و 3 ساعت{RLM}'
        )
        self.assertEqual(format_duration(timedelta(hours=5)), f'{RLM}5 ساعت{RLM}')
        self.assertEqual(format_duration(timedelta(minutes=12)), f'{RLM}12 دقیقه{RLM}')
        self.assertEqual(format_duration(timedelta(seconds=10)), f'{RLM}کمتر از 1 دقیقه{RLM}')

    def test_jalali_filter_accepts_a_plain_date(self):
        day = timezone.localdate()
        self.assertEqual(
            jalali(day, '%Y/%m/%d'), jdatetime.date.fromgregorian(date=day).strftime('%Y/%m/%d'),
        )

    def export(self, **params):
        self.client.login(username='t_admin', password=PASSWORD)
        return self.client.get(reverse('technician_report'), {'export': '1', **params})

    def test_export_has_both_sheets(self):
        self.job(self.tech, 2, Job.Status.SUBMITTED)
        response = self.export(date_from='', date_to='')
        workbook = load_workbook(io.BytesIO(response.content))
        self.assertEqual(workbook.sheetnames, [SUMMARY_SHEET, DETAIL_SHEET])
        self.assertEqual(workbook[SUMMARY_SHEET].max_row, 3 + 2)   # two technicians
        self.assertEqual(workbook[DETAIL_SHEET].max_row, 3 + 1)    # one job
        self.assertIn('بازه ارجاع', workbook[SUMMARY_SHEET]['A1'].value)

    def test_export_for_an_empty_period_still_lists_technicians(self):
        self.job(self.tech, 2, Job.Status.SUBMITTED)
        response = self.export(date_from='1300/01/01', date_to='1300/01/02')
        workbook = load_workbook(io.BytesIO(response.content))
        self.assertEqual(workbook[DETAIL_SHEET].max_row, 3)         # headers only
        self.assertEqual(workbook[SUMMARY_SHEET].max_row, 3 + 2)

    def test_reversed_period_is_refused(self):
        response = self.export(date_from='1405/08/20', date_to='1405/08/10')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'تاریخ شروع')

    def test_formula_in_a_customer_name_stays_text(self):
        self.customer.full_name = '=1+1'
        self.customer.save()
        self.job(self.tech, 2, Job.Status.SUBMITTED)
        workbook = load_workbook(io.BytesIO(self.export().content))
        cell = workbook[DETAIL_SHEET]['C4']
        self.assertEqual(cell.value, '=1+1')
        self.assertEqual(cell.data_type, 's')

    def test_technicians_cannot_open_the_report(self):
        self.client.login(username='t_tech', password=PASSWORD)
        self.assertEqual(self.client.get(reverse('technician_report')).status_code, 403)











class ModemStepTests(JobTestBase):
    def service_delivery_job(self):
        return self.make_job(
            'installation', 'service_delivery',
            latitude=Decimal('35.1'), longitude=Decimal('51.1'),
            upload_mbps=Decimal('10'), download_mbps=Decimal('20'),
        )

    def test_modem_screen_has_no_quantity_box_and_records_one(self):
        job = self.service_delivery_job()
        self.client.login(username='t_tech', password=PASSWORD)
        url = reverse('job_step', args=[job.pk, 2])     # the modem step
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'name="qty_M018"')

        self.client.post(url, {'select_M018': 'on'})
        usage = job.material_usages.get()
        self.assertEqual((usage.material_code, usage.quantity), ('M018', Decimal('1')))

    def test_choosing_both_modems_is_refused(self):
        job = self.service_delivery_job()
        self.client.login(username='t_tech', password=PASSWORD)
        self.client.post(
            reverse('job_step', args=[job.pk, 2]), {'select_M018': 'on', 'select_M019': 'on'},
        )
        self.assertEqual(job.material_usages.count(), 0)


class SupportJobCreateTests(JobTestBase):
    def post_job(self, **data):
        self.client.login(username='t_admin', password=PASSWORD)
        body = {
            'job_type': 'installation', 'workflow': 'fusion',
            'assigned_operator': self.tech.pk, 'customer': self.customer.pk,
        }
        body.update(data)
        return self.client.post(reverse('job_create'), body)

    def test_the_same_installation_workflow_cannot_be_given_to_a_customer_twice(self):
        self.assertEqual(self.post_job().status_code, 302)
        response = self.post_job()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'قبلاً این نوع کار نصب')
        self.assertEqual(Job.objects.filter(customer=self.customer, workflow='fusion').count(), 1)

    def test_a_different_workflow_for_the_same_customer_is_fine(self):
        self.post_job()
        self.assertEqual(self.post_job(workflow='drop_cable').status_code, 302)

    def test_malfunction_repair_can_repeat(self):
        for _ in range(2):
            response = self.post_job(job_type='malfunction_repair', workflow='malfunction')
            self.assertEqual(response.status_code, 302)
        self.assertEqual(Job.objects.filter(customer=self.customer, workflow='malfunction').count(), 2)

    def test_page_gives_the_filters_what_they_need(self):
        self.make_job('installation', 'fusion')
        self.client.login(username='t_admin', password=PASSWORD)
        response = self.client.get(reverse('job_create'))
        self.assertContains(response, f'data-city="{self.customer.city_id}"')
        self.assertEqual(response.context['taken_map'], {self.customer.pk: ['fusion']})


class ContinueWorkflowTests(JobTestBase):
    def submitted(self, workflow, status=Job.Status.SUBMITTED):
        return self.make_job('installation', workflow, status=status)

    def test_which_workflow_follows_which(self):
        self.assertEqual(self.submitted('ftth_inquiry').next_workflow(), 'drop_cable')
        self.assertEqual(self.submitted('drop_cable').next_workflow(), 'fusion')
        self.assertEqual(self.submitted('fusion').next_workflow(), 'service_delivery')
        self.assertIsNone(self.submitted('service_delivery').next_workflow())   # the end of the chain

    def test_nothing_follows_an_unfinished_job_or_a_job_without_a_customer(self):
        self.assertIsNone(self.make_job('installation', 'ftth_inquiry').next_workflow())
        orphan = self.submitted('ftth_inquiry')
        Job.objects.filter(pk=orphan.pk).update(customer=None)
        orphan.refresh_from_db()
        self.assertIsNone(orphan.next_workflow())

    def test_technician_continues_with_the_next_workflow(self):
        job = self.submitted('ftth_inquiry')
        self.client.login(username='t_tech', password=PASSWORD)
        response = self.client.post(reverse('job_continue', args=[job.pk]))
        new_job = Job.objects.get(customer=self.customer, workflow='drop_cable')
        self.assertRedirects(
            response, reverse('job_start', args=[new_job.pk]), fetch_redirect_response=False,
        )
        self.assertEqual(new_job.assigned_operator, self.tech)
        self.assertEqual(new_job.created_by, self.tech)
        self.assertEqual(new_job.job_type, 'installation')
        self.assertEqual(new_job.status, Job.Status.ASSIGNED)
        self.assertFalse(Notification.objects.filter(job=new_job).exists())  # no notice for yourself

    def test_continuing_twice_does_not_create_a_second_job(self):
        job = self.submitted('ftth_inquiry')
        self.client.login(username='t_tech', password=PASSWORD)
        self.client.post(reverse('job_continue', args=[job.pk]))
        self.client.post(reverse('job_continue', args=[job.pk]))
        self.assertEqual(Job.objects.filter(customer=self.customer, workflow='drop_cable').count(), 1)

    def test_an_existing_follow_up_job_blocks_a_duplicate(self):
        job = self.submitted('ftth_inquiry')
        self.make_job('installation', 'drop_cable', operator=self.other_tech)  # support already referred it
        self.client.login(username='t_tech', password=PASSWORD)
        self.client.post(reverse('job_continue', args=[job.pk]))
        self.assertEqual(Job.objects.filter(customer=self.customer, workflow='drop_cable').count(), 1)

    def test_other_technicians_and_unfinished_jobs_cannot_continue(self):
        job = self.submitted('ftth_inquiry')
        self.client.login(username='t_other', password=PASSWORD)
        self.assertEqual(self.client.post(reverse('job_continue', args=[job.pk])).status_code, 404)

        draft = self.make_job('installation', 'ftth_inquiry')
        self.client.login(username='t_tech', password=PASSWORD)
        self.client.post(reverse('job_continue', args=[draft.pk]))
        self.assertFalse(Job.objects.filter(workflow='drop_cable').exists())

    def test_home_shows_the_continue_button(self):
        self.submitted('ftth_inquiry')
        self.client.login(username='t_tech', password=PASSWORD)
        self.assertContains(self.client.get(reverse('operator_home')), 'ادامه: دراپ کشی')

    def test_continuing_after_fusion_starts_service_delivery(self):
        job = self.submitted('fusion')
        self.client.login(username='t_tech', password=PASSWORD)
        self.client.post(reverse('job_continue', args=[job.pk]))
        self.assertTrue(Job.objects.filter(customer=self.customer, workflow='service_delivery').exists())


class LastStepButtonTests(JobTestBase):
    def test_button_appears_on_earlier_steps_only_and_the_progress_bar_links_back(self):
        job = self.make_job(
            'installation', 'ftth_inquiry', ftth_outcome='needs_materials',
            latitude=Decimal('35.1'), longitude=Decimal('51.1'),
        )
        # Location and the outcome are done, so the photos step (index 1) is where work stands
        current = reverse('job_step', args=[job.pk, 1])
        self.client.login(username='t_tech', password=PASSWORD)

        earlier = self.client.get(reverse('job_step', args=[job.pk, 0]))
        self.assertContains(earlier, 'آخرین مرحله')
        self.assertContains(earlier, f'href="{current}"')
        self.assertContains(earlier, f'href="{reverse("job_location", args=[job.pk])}"')

        here = self.client.get(current)
        self.assertNotContains(here, 'آخرین مرحله')



    def test_previous_step_button_goes_one_step_back(self):
        job = self.make_job(
            'installation', 'ftth_inquiry', ftth_outcome='needs_materials',
            latitude=Decimal('35.1'), longitude=Decimal('51.1'),
        )
        location = reverse('job_location', args=[job.pk])
        first = reverse('job_step', args=[job.pk, 0])
        second = reverse('job_step', args=[job.pk, 1])
        self.client.login(username='t_tech', password=PASSWORD)

        self.assertNotContains(self.client.get(location), 'مرحله قبل')   # nothing comes before the location
        self.assertContains(self.client.get(first), f'href="{location}">مرحله قبل')
        self.assertContains(self.client.get(second), f'href="{first}">مرحله قبل')




class DashboardSortTests(JobTestBase):
    def submitted_job(self, minutes_ago):
        job = self.make_job('installation', 'fusion')
        Job.objects.filter(pk=job.pk).update(
            status=Job.Status.SUBMITTED, submitted_at=timezone.now() - timedelta(minutes=minutes_ago),
        )
        return job

    def page(self, **params):
        self.client.login(username='t_admin', password=PASSWORD)
        return self.client.get(reverse('support_dashboard'), params)

    def test_newest_submission_first_by_default_and_reversible(self):
        old, new = self.submitted_job(60), self.submitted_job(5)
        self.assertEqual([j.pk for j in self.page().context['page']], [new.pk, old.pk])
        self.assertEqual(
            [j.pk for j in self.page(sort='submitted', dir='asc').context['page']], [old.pk, new.pk],
        )

    def test_sorting_keeps_the_default_status_filter(self):
        self.submitted_job(5)
        draft = self.make_job('installation', 'fusion')      # not submitted
        ids = [j.pk for j in self.page(sort='submitted', dir='asc').context['page']]
        self.assertNotIn(draft.pk, ids)

    def test_page_two_keeps_the_default_status_filter(self):
        for minutes in range(21):
            self.submitted_job(minutes + 1)
        self.make_job('installation', 'fusion')              # not submitted
        page_two = self.page(page=2).context['page']
        self.assertTrue(all(job.status == 'submitted' for job in page_two))

    def test_header_link_and_icons(self):
        page = self.page()
        self.assertContains(page, 'href="?sort=submitted&amp;dir=asc"')
        for icon in ('clipboard-plus', 'chart-no-axes-combined'):
            self.assertContains(page, f'data-lucide="{icon}"')