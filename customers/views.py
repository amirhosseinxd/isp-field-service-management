
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from accounts.models import User
from accounts.permissions import role_required
from jobs.models import JobEvidence
from jobs.views import paginate

from .forms import CustomerFilterForm, CustomerForm
from .models import Customer


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
        .select_related('job')
        .order_by('-uploaded_at')
    )
    page, qs = paginate(request, media, 24)
    return render(request, 'customers/customer_detail.html', {
        'customer': customer, 'jobs': jobs, 'page': page, 'qs': qs,
    })
# Create your views here.
