from datetime import datetime

import jdatetime
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from jobs.models import Job

from .imports import import_rows, parse_row
from .models import City, Customer
from datetime import timedelta

from django.db.models import Max

from accounts.templatetags.jalali_tags import time_ago

import io

from django.urls import reverse
from openpyxl import load_workbook

from inventory.models import Material
from jobs.models import Job, JobEvidence, JobMaterialUsage

from .filters import apply_filters, base_customers
from .forms import CustomerFilterForm

def make_customer(**overrides):
    data = dict(
        subscription_id='0012345678', full_name='علی', mobile='09120000000',
        address='آدرس', city=City.objects.get(name='گرمسار'),
        center_number='03', registered_at=timezone.now(),
    )
    data.update(overrides)
    return Customer(**data)


class CustomerModelTests(TestCase):
    def test_subscription_id_must_be_ten_digits(self):
        with self.assertRaises(ValidationError):
            make_customer(subscription_id='123').full_clean()

    def test_center_is_built_from_city_and_number(self):
        self.assertEqual(make_customer().center, 'گرمسار-OAC.03')

    def test_status_falls_back_to_label_when_no_jobs(self):
        customer = make_customer(status_label='در انتظار')
        customer.save()
        self.assertEqual(customer.current_status_display(), 'در انتظار')

    def test_customer_with_jobs_cannot_be_deleted(self):
        customer = make_customer()
        customer.save()
        admin = User.objects.create_user(username='c_admin', password='x', role=User.Role.ADMIN)
        tech = User.objects.create_user(username='c_tech', password='x', role=User.Role.OPERATOR)
        Job.objects.create(
            job_type='installation', workflow='drop_cable', assigned_operator=tech,
            created_by=admin, customer=customer,
        )
        with self.assertRaises(ProtectedError):
            customer.delete()


def excel_row(**overrides):
    """One row as openpyxl returns it, using the real column layout."""
    values = {
        'subscription_id': 16473825,        # Excel dropped the leading zeros
        'full_name': 'ستار مطلبی نژاد',
        'mobile': 9371868151,               # Excel dropped the leading 0
        'address': 'ولی عصر',
        'city': 'میامی',
        'center': 'میامی-OAC.01',
        'registered_at': '12:20:09-1405/08/18',
        'status': 'در انتظار بررسی',
    }
    values.update(overrides)
    return values


class ExcelImportTests(TestCase):
    def test_leading_zeros_are_restored(self):
        data = parse_row(excel_row())
        self.assertEqual(data['subscription_id'], '0016473825')
        self.assertEqual(data['mobile'], '09371868151')

    def test_jalali_date_is_converted_to_gregorian(self):
        data = parse_row(excel_row())
        local = timezone.localtime(data['registered_at'])
        self.assertEqual(local.date(), jdatetime.date(1405, 8, 18).togregorian())
        self.assertEqual((local.hour, local.minute), (12, 20))

    def test_bad_city_is_reported_and_not_saved(self):
        summary = import_rows([(2, excel_row(city='شهر نامعتبر'))])
        self.assertEqual(summary['created'], 0)
        self.assertEqual(len(summary['errors']), 1)
        self.assertEqual(Customer.objects.count(), 0)

    def test_blank_row_is_skipped_quietly(self):
        blank = {key: None for key in excel_row()}
        summary = import_rows([(2, blank)])
        self.assertEqual(summary, {'created': 0, 'updated': 0, 'errors': []})

    def test_reimport_updates_instead_of_duplicating(self):
        import_rows([(2, excel_row())])
        summary = import_rows([(2, excel_row())])
        self.assertEqual(summary['created'], 0)
        self.assertEqual(summary['updated'], 1)
        self.assertEqual(Customer.objects.count(), 1)

    def test_good_and_bad_rows_in_one_file(self):
        summary = import_rows([
            (2, excel_row()),
            (3, excel_row(subscription_id='abc')),
        ])
        self.assertEqual(summary['created'], 1)
        self.assertEqual(len(summary['errors']), 1)
        self.assertEqual(summary['errors'][0][0], 3)  # the error names row 3

    def test_city_matches_whatever_the_spacing_or_letter_form(self):
        expected = City.objects.get(name__startswith='مهدی')
        for spelling in ('مهدی شهر', 'مهدی‌شهر', 'مهدیشهر', ' مهدی شهر ', 'مهدي شهر'):
            with self.subTest(spelling=spelling):
                data = parse_row(excel_row(city=spelling, center='مهدی‌شهر-OAC.02'))
                self.assertEqual(data['city'], expected)

        self.assertEqual(
            parse_row(excel_row(city='كلاته خيج'))['city'],     # Arabic letter forms
            City.objects.get(name='کلاته خیج'),
        )








class LastActivityTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='l_admin', password='x', role=User.Role.ADMIN)
        self.tech = User.objects.create_user(username='l_tech', password='x', role=User.Role.OPERATOR)
        self.customer = make_customer()
        self.customer.save()

    def make_job(self):
        return Job.objects.create(
            job_type='installation', workflow='ftth_inquiry', assigned_operator=self.tech,
            created_by=self.admin, customer=self.customer, ftth_outcome='feasible',
        )

    def last_activity(self):
        return Customer.objects.annotate(last=Max('jobs__updated_at')).get(pk=self.customer.pk).last

    def make_old(self, *jobs):
        old = timezone.now() - timedelta(days=5)
        Job.objects.filter(pk__in=[j.pk for j in jobs]).update(updated_at=old)
        return old

    def test_customer_without_jobs_has_no_activity(self):
        self.assertIsNone(self.last_activity())

    def test_activity_follows_the_newest_change_across_all_jobs(self):
        first, second = self.make_job(), self.make_job()
        old = self.make_old(first, second)
        first.status = Job.Status.IN_PROGRESS
        first.save(update_fields=['status'])  # a partial save must still count
        first.refresh_from_db()
        self.assertEqual(self.last_activity(), first.updated_at)
        self.assertGreater(first.updated_at, old)

    def test_review_counts_as_activity(self):
        job = self.make_job()
        job.submit(self.tech, 'desc')
        old = self.make_old(job)
        job.refresh_from_db()
        job.mark_reviewed(self.admin)  # this one bypasses save()
        job.refresh_from_db()
        self.assertGreater(job.updated_at, old)

    def test_uploading_evidence_counts_as_activity(self):
        job = self.make_job()
        old = self.make_old(job)
        JobEvidence.objects.create(
            job=job, kind='photo', category='general', file='x.jpg', uploaded_by=self.tech,
        )
        job.refresh_from_db()
        self.assertGreater(job.updated_at, old)


class TimeAgoFilterTests(TestCase):
    def test_uses_largest_unit_and_persian_digits(self):
        now = timezone.now()
        self.assertEqual(time_ago(now - timedelta(hours=3, minutes=10)), '۳ ساعت پیش')
        self.assertEqual(time_ago(now - timedelta(days=2, hours=1)), '۲ روز پیش')
        self.assertEqual(time_ago(now - timedelta(seconds=5)), 'لحظاتی پیش')
        self.assertEqual(time_ago(None), '')








class MaterialFilterAndSelectionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='f_admin', password='pw-12345-test', role=User.Role.ADMIN)
        self.tech = User.objects.create_user(username='f_tech', password='pw-12345-test', role=User.Role.OPERATOR)

        def customer(number, name):
            c = make_customer(subscription_id=number, full_name=name)
            c.save()
            return c

        self.splitter16 = customer('0000000001', 'الف')
        self.splitter8 = customer('0000000002', 'ب')
        self.wire = customer('0000000003', 'ج')
        self.unfinished = customer('0000000004', 'د')   # used a splitter, but the job isn't finished
        self.needed_only = customer('0000000005', 'ه')  # splitter only listed as "needed"

        self.use(self.splitter16, 'M012')
        self.use(self.splitter8, 'M013')
        self.use(self.wire, 'M005')
        self.use(self.unfinished, 'M012', status=Job.Status.IN_PROGRESS)
        self.use(self.needed_only, 'M012', purpose='needed')

    def use(self, customer, code, status=Job.Status.SUBMITTED, purpose='used'):
        job = Job.objects.create(
            job_type='installation', workflow='ftth_inquiry', assigned_operator=self.tech,
            created_by=self.admin, customer=customer, status=status,
        )
        JobMaterialUsage.objects.create(
            job=job, material=Material.objects.get(code=code), quantity=1, purpose=purpose,
        )

    def ids_for(self, **params):
        form = CustomerFilterForm(params)
        self.assertTrue(form.is_valid(), form.errors)
        return set(apply_filters(base_customers(), form).values_list('pk', flat=True))

    def test_splitter_group_matches_either_splitter(self):
        self.assertEqual(self.ids_for(material='g_splitter'), {self.splitter16.pk, self.splitter8.pk})


    def test_single_material_matches_only_that_material(self):
        self.assertEqual(self.ids_for(material='M005'), {self.wire.pk})
        self.assertEqual(self.ids_for(material='M009'), set())  # nobody used a hook

    def test_grouped_materials_are_not_offered_on_their_own(self):
        # By design, both splitters live in the single "اسپلیتر" option
        for code in ('M012', 'M013'):
            with self.subTest(code=code):
                self.assertFalse(CustomerFilterForm({'material': code}).is_valid())

    
    def test_material_filter_combines_with_other_filters(self):
        self.assertEqual(self.ids_for(material='g_splitter', q='ب'), {self.splitter8.pk})

    def read_ids(self, response):
        sheet = load_workbook(io.BytesIO(response.content)).active
        return {row[0].value for row in sheet.iter_rows(min_row=3)}

    def test_export_with_filter_exports_everything_that_matches(self):
        self.client.login(username='f_admin', password='pw-12345-test')
        response = self.client.get(reverse('customer_export'), {'material': 'g_splitter'})
        self.assertEqual(self.read_ids(response), {1, 2})

    def test_export_of_selected_customers_only_includes_them(self):
        self.client.login(username='f_admin', password='pw-12345-test')
        response = self.client.post(
            reverse('customer_export'), {'ids': f'{self.wire.pk},{self.needed_only.pk},abc'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.read_ids(response), {3, 5})

    def test_technician_cannot_export(self):
        self.client.login(username='f_tech', password='pw-12345-test')
        self.assertEqual(self.client.post(reverse('customer_export'), {'ids': '1'}).status_code, 403)