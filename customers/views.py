
from django.contrib import messages
from django.db.models import Q,Count
from django.shortcuts import get_object_or_404, redirect, render

from accounts.models import User
from accounts.permissions import role_required
from jobs.models import JobEvidence
from jobs.views import paginate

from .forms import CustomerFilterForm, CustomerForm, ExcelUploadForm
from .models import Customer

import openpyxl
from .imports import import_rows,COLUMNS


def _warn_if_duplicate_mobile(request, customer):
    duplicates = Customer.objects.filter(mobile=customer.mobile).exclude(pk=customer.pk)
    if duplicates.exists():
        names = '، '.join(c.full_name for c in duplicates[:3])
        messages.warning(
            request, f'توجه: این شماره موبایل برای مشتری دیگری نیز ثبت شده است: {names}',
        )


@role_required(User.Role.ADMIN)
def customer_list(request):
    form = CustomerFilterForm(request.GET or None)
    customers = Customer.objects.select_related('city')
    if form.is_valid():
        q = form.cleaned_data['q']
        city = form.cleaned_data['city']
        if q:
            customers = customers.filter(
                Q(subscription_id__icontains=q)
                | Q(full_name__icontains=q)
                | Q(mobile__icontains=q)
            )
        if city:
            customers = customers.filter(city=city)

    page, qs = paginate(request, customers, 20)
    return render(request, 'customers/customer_list.html', {'form': form, 'page': page, 'qs': qs})


@role_required(User.Role.ADMIN)
def customer_create(request):
    form = CustomerForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        customer = form.save()
        _warn_if_duplicate_mobile(request, customer)
        messages.success(request, 'مشتری ثبت شد.')
        return redirect('customer_detail', pk=customer.pk)
    return render(request, 'customers/customer_form.html', {'form': form, 'is_new': True})



@role_required(User.Role.ADMIN)
def customer_import(request):
    form = ExcelUploadForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        try:
            workbook = openpyxl.load_workbook(form.cleaned_data['excel_file'], data_only=True)
        except Exception:
            form.add_error('excel_file', 'فایل اکسل قابل خواندن نیست.')
        else:
            sheet = workbook.active
            rows = (
                (row_number, {
                    key: sheet[f'{letter}{row_number}'].value
                    for key, letter in COLUMNS.items()
                })
                for row_number in range(2, sheet.max_row + 1)
            )
            summary = import_rows(rows)
            summary['duplicate_mobile_count'] = (
                Customer.objects.exclude(mobile='')
                .values('mobile')
                .annotate(n=Count('id'))
                .filter(n__gt=1)
                .count()
            )
            return render(request, 'customers/customer_import_result.html', {'summary': summary})

    return render(request, 'customers/customer_import.html', {'form': form})


@role_required(User.Role.ADMIN)
def customer_edit(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    form = CustomerForm(request.POST or None, instance=customer)
    if request.method == 'POST' and form.is_valid():
        form.save()
        _warn_if_duplicate_mobile(request, customer)
        messages.success(request, 'اطلاعات مشتری به‌روزرسانی شد.')
        return redirect('customer_detail', pk=customer.pk)
    return render(request, 'customers/customer_form.html', {
        'form': form, 'is_new': False, 'customer': customer,
    })


@role_required(User.Role.ADMIN)
def customer_detail(request, pk):
    customer = get_object_or_404(Customer.objects.select_related('city'), pk=pk)
    jobs = customer.jobs.order_by('-created_at')
    media = (
        JobEvidence.objects.filter(job__customer=customer)
        .select_related('job', 'uploaded_by')
        .order_by('-uploaded_at')
    )
    page, qs = paginate(request, media, 24)
    return render(request, 'customers/customer_detail.html', {
        'customer': customer, 'jobs': jobs, 'page': page, 'qs': qs,
    })
# Create your views here.
