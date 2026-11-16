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
            job_type='repair', workflow='drop_cable', assigned_operator=tech,
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