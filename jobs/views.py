
from django.contrib import messages
import mimetypes
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.db import transaction
from inventory.models import Material
from accounts.models import User
from accounts.permissions import role_required

import jdatetime
from .reports import build_report_workbook, collect_report
from . import wizard, workflows
from .forms import (
    MAX_PHOTOS_PER_STAGE, FtthOutcomeForm, JobCreateForm, JobFilterForm, LocationForm,
    MaterialsSelectionForm, PhotoFilterForm, PhotoForm, ReportForm, SpeedQuestionForm,
    VideoForm, YesNoQuestionForm,ReturnForm,ReportPeriodForm
)

from .models import Job, JobEvidence, JobMaterialUsage

import os
import re
from .review import review_sections
from .forms import (
    MAX_PHOTOS_PER_STAGE, JobFilterForm, LocationForm, PhotoFilterForm, PhotoForm, ReportForm,
)
from audit.models import AuditEntry
from audit.services import log as audit_log



CLOSED = (Job.Status.SUBMITTED, Job.Status.REVIEWED)




def get_operator_job(request, pk):
    return get_object_or_404(
        Job.objects.select_related('customer__city'),
        pk=pk, assigned_operator=request.user,
    )




@role_required(User.Role.OPERATOR)
def operator_home(request):
    mine = Job.objects.filter(assigned_operator=request.user).select_related('customer')
    return render(request, 'jobs/operator_home.html', {
        'active_jobs': mine.exclude(status__in=CLOSED),
        'submitted_jobs': mine.filter(status__in=CLOSED)[:10],
    })


@role_required(User.Role.OPERATOR)
def job_start(request, pk):
    job = get_operator_job(request, pk)
    if job.status in CLOSED:
        messages.info(request, 'این کار قبلاً ارسال شده است.')
        return redirect('operator_home')
    if job.status == Job.Status.ASSIGNED:
        job.status = Job.Status.IN_PROGRESS
        job.save(update_fields=['status'])
    return redirect(wizard.next_url(job))


@role_required(User.Role.OPERATOR)
def job_location(request, pk):
    job = get_operator_job(request, pk)
    if job.status in CLOSED:
        messages.info(request, 'این کار قبلاً ارسال شده است.')
        return redirect('operator_home')
    if job.status == Job.Status.ASSIGNED:
        job.status = Job.Status.IN_PROGRESS
        job.save(update_fields=['status'])

    form = LocationForm(
        request.POST or None,
        initial={
            'latitude': job.latitude,
            'longitude': job.longitude,
            'source': job.location_source or 'manual',
        },
    )
    if request.method == 'POST' and form.is_valid():
        job.latitude = form.cleaned_data['latitude']
        job.longitude = form.cleaned_data['longitude']
        job.location_source = form.cleaned_data['source']
        job.save(update_fields=['latitude', 'longitude', 'location_source'])
        return redirect(wizard.next_url(job))

    return render(request, 'jobs/step_location.html', {
        'job': job, 'form': form, 'steps': wizard.progress(job),
    })



QUESTION_FORMS = {
    'ftth_outcome': FtthOutcomeForm,
    'fat_needs_splitter': YesNoQuestionForm,
    'tokar_used': YesNoQuestionForm,
    'materials_used': YesNoQuestionForm,
    'upload_mbps': SpeedQuestionForm,
    'download_mbps': SpeedQuestionForm,
}


def _question_view(request, job, index, step):
    form_class = QUESTION_FORMS[step.field_name]
    if request.method == 'POST':
        form = form_class(request.POST)
        if form.is_valid():
            setattr(job, step.field_name, form.cleaned_data['answer'])
            job.save(update_fields=[step.field_name])
            return redirect(wizard.next_url(job))
    else:
        current_answer = getattr(job, step.field_name)
        form = form_class(initial={
            'answer': current_answer if current_answer not in (None, '') else None,
        })
    return render(request, 'jobs/step_question.html', {
        'job': job, 'step': step, 'form': form, 'steps': wizard.progress(job, index),
    })


def _description_view(request, job, index, step):
    if request.method == 'POST':
        form = ReportForm(request.POST)
        if form.is_valid():
            try:
                job.submit(request.user, form.cleaned_data['description'])
            except (ValueError, PermissionError) as exc:
                messages.error(request, str(exc))
                return redirect(wizard.step_url(job, index))
            messages.success(request, 'کار با موفقیت ارسال شد.')
            return redirect('operator_home')
    else:
        existing = getattr(job, 'report', None)
        form = ReportForm(initial={'description': existing.description if existing else ''})
    return render(request, 'jobs/step_description.html', {
        'job': job, 'form': form,
        'missing': workflows.missing_before_description(job),
        'steps': wizard.progress(job, index),
    })



def _photo_view(request, job, index, step):
    is_video = step.kind == JobEvidence.Kind.VIDEO
    form_class = VideoForm if is_video else PhotoForm
    form = form_class(request.POST or None, request.FILES or None)

    # Videos default to 3 uploads, photos to the shared per-stage limit
    limit = step.maximum or (3 if is_video else MAX_PHOTOS_PER_STAGE)
    existing = step.count(job)

    if request.method == 'POST' and form.is_valid():
        files = [form.cleaned_data['video']] if is_video else form.cleaned_data['images']
        if existing + len(files) > limit:
            form.add_error(None, f'حداکثر {limit} مورد برای این مرحله مجاز است.')
        else:
            for uploaded in files:
                JobEvidence.objects.create(
                    job=job, kind=step.kind, category=step.category,
                    file=uploaded, uploaded_by=request.user,
                )
            messages.success(request, 'ثبت شد.')
            return redirect(wizard.step_url(job, index))

    return render(request, 'jobs/step_photo.html', {
        'job': job,
        'index': index,
        'step': step,
        'form': form,
        'items': job.evidence.filter(kind=step.kind, category=step.category),
        'count': existing,
        'complete': step.is_complete(job),
        'next_url': wizard.next_url(job),
        'steps': wizard.progress(job, index),
    })



def _materials_view(request, job, index, step):
    materials = Material.objects.filter(code__in=step.allowed_codes).order_by('code')

    if request.method == 'POST':
        form = MaterialsSelectionForm(request.POST, materials=materials, step=step)
        if form.is_valid():
            # Replace this step's old rows, so unchecking an item removes it
            with transaction.atomic():
                step.usages(job).delete()
                for material, quantity in form.selected:
                    JobMaterialUsage.objects.create(
                        job=job, material=material, quantity=quantity, purpose=step.purpose,
                    )
            messages.success(request, 'ثبت شد.')
            return redirect(wizard.next_url(job))
    else:
        saved = {u.material_id: u.quantity for u in step.usages(job)}
        initial = {}
        for m in materials:
            if m.pk in saved:
                initial[f'select_{m.code}'] = True
                initial[f'qty_{m.code}'] = saved[m.pk]
        form = MaterialsSelectionForm(initial=initial, materials=materials, step=step)

    return render(request, 'jobs/step_materials.html', {
        'job': job,
        'index': index,
        'step': step,
        'form': form,
        'complete': step.is_complete(job),
        'next_url': wizard.next_url(job),
        'steps': wizard.progress(job, index),
    })




@role_required(User.Role.OPERATOR)
@require_POST
def job_evidence_delete(request, pk, index, evidence_pk):
    job = get_operator_job(request, pk)
    if job.status in CLOSED:
        messages.error(request, 'بعد از ارسال کار، حذف ممکن نیست.')
        return redirect('operator_home')

    evidence = get_object_or_404(JobEvidence, pk=evidence_pk, job=job)
    audit_log(
        request.user, AuditEntry.Action.EVIDENCE_DELETED, job,
        details=f'{evidence.get_kind_display()} — {evidence.get_category_display()}',
    )
    storage, name = evidence.file.storage, evidence.file.name
    evidence.delete()       # database row first
    storage.delete(name)    # then the file on disk
    messages.success(request, 'حذف شد.')
    return redirect(wizard.step_url(job, index))


@role_required(User.Role.OPERATOR)
def job_step(request, pk, index):
    job = get_operator_job(request, pk)
    if job.status in CLOSED:
        messages.info(request, 'این کار قبلاً ارسال شده است.')
        return redirect('operator_home')
    if not job.has_location:
        return redirect('job_location', pk=job.pk)

    steps = workflows.steps_for(job)
    if index < 0 or index >= len(steps):
        raise Http404
    step = steps[index]

    # Steps can be revisited once they're done, but never skipped ahead to
    current = wizard.current_index(job)
    if not step.applies_to(job) or (current is not None and index > current):
        messages.warning(request, 'ابتدا مرحله قبلی را کامل کنید.')
        return redirect(wizard.next_url(job))

    if job.status == Job.Status.ASSIGNED:
        job.status = Job.Status.IN_PROGRESS
        job.save(update_fields=['status'])

    if isinstance(step, workflows.QuestionStep):
        return _question_view(request, job, index, step)
    if isinstance(step, workflows.DescriptionStep):
        return _description_view(request, job, index, step)
    if isinstance(step, workflows.PhotoStep):
        return _photo_view(request, job, index, step)
    return _materials_view(request, job, index, step)






def paginate(request, queryset, per_page):
    page = Paginator(queryset, per_page).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return page, params.urlencode()


@login_required
def job_photo(request, pk):
    """Serve a photo file only to support admins and the job's own operator."""
    photo = get_object_or_404(JobEvidence.objects.select_related('job'), pk=pk)
    user = request.user
    allowed = user.role == User.Role.ADMIN or photo.job.assigned_operator_id == user.id
    if not allowed:
        raise Http404
    try:
        file = photo.file.open('rb')
    except FileNotFoundError:
        raise Http404
    content_type = mimetypes.guess_type(photo.file.name)[0] or 'application/octet-stream'
    response = FileResponse(file, content_type=content_type)
    response['Cache-Control'] = 'private, max-age=3600'
    response['X-Content-Type-Options'] = 'nosniff'
    return response




RANGE_RE = re.compile(r'bytes=(\d*)-(\d*)')

@login_required
def job_video(request, pk):
    """Serve a video file with HTTP range support, to the admins and the job's own operator."""
    evidence = get_object_or_404(JobEvidence.objects.select_related('job'), pk=pk)
    if evidence.kind != JobEvidence.Kind.VIDEO:
        raise Http404
    user = request.user
    allowed = user.role == User.Role.ADMIN or evidence.job.assigned_operator_id == user.id
    if not allowed:
        raise Http404

    try:
        size = evidence.file.size
    except FileNotFoundError:
        raise Http404
    content_type = mimetypes.guess_type(evidence.file.name)[0] or 'application/octet-stream'

    range_header = request.headers.get('Range', '')
    match = RANGE_RE.match(range_header)
    if not match:
        # No range requested: send the whole file, but say we support ranges
        response = FileResponse(evidence.file.open('rb'), content_type=content_type)
        response['Content-Length'] = size
        response['Accept-Ranges'] = 'bytes'
        response['Cache-Control'] = 'private, max-age=3600'
        response['X-Content-Type-Options'] = 'nosniff'
        return response

    start_str, end_str = match.groups()
    start = int(start_str) if start_str else 0
    end = int(end_str) if end_str else size - 1
    end = min(end, size - 1)

    if start >= size or start > end:
        response = FileResponse(evidence.file.open('rb'))
        response.status_code = 416
        response['Content-Range'] = f'bytes */{size}'
        return response

    file = evidence.file.open('rb')
    file.seek(start)
    length = end - start + 1
    response = FileResponse(
        iter(lambda: file.read(min(65536, length - file.tell() + start)) if file.tell() - start < length else b'', b''),
        content_type=content_type,
        status=206,
    )
    response['Content-Length'] = length
    response['Content-Range'] = f'bytes {start}-{end}/{size}'
    response['Accept-Ranges'] = 'bytes'
    response['Cache-Control'] = 'private, max-age=3600'
    response['X-Content-Type-Options'] = 'nosniff'
    return response



@role_required(User.Role.ADMIN)
def support_dashboard(request):
    # With no filters in the URL, show submitted jobs (the review queue)
    form = JobFilterForm(request.GET or {'status': Job.Status.SUBMITTED})
    jobs = (
        Job.objects.select_related('assigned_operator', 'customer')
        .annotate(photo_total=Count('evidence'))
        .order_by(F('submitted_at').desc(nulls_last=True), '-created_at')
    )
    if form.is_valid():
        cd = form.cleaned_data
        if cd['status']:
            jobs = jobs.filter(status=cd['status'])
        if cd['job_type']:
            jobs = jobs.filter(job_type=cd['job_type'])
        if cd['workflow']:
            jobs = jobs.filter(workflow=cd['workflow'])
        if cd['operator']:
            jobs = jobs.filter(assigned_operator=cd['operator'])
        if cd['customer_q']:
            q = cd['customer_q']
            jobs = jobs.filter(
                Q(customer__full_name__icontains=q) | Q(customer__subscription_id__icontains=q)
            )
        if cd['date_from']:
            jobs = jobs.filter(submitted_at__date__gte=cd['date_from'])
        if cd['date_to']:
            jobs = jobs.filter(submitted_at__date__lte=cd['date_to'])

    page, qs = paginate(request, jobs, 20)
    return render(request, 'jobs/support_dashboard.html', {
        'form': form,
        'page': page,
        'qs': qs,
        'pending_count': Job.objects.filter(status=Job.Status.SUBMITTED).count(),
    })


@role_required(User.Role.ADMIN)
def support_job_detail(request, pk):
    job = get_object_or_404(
        Job.objects.select_related(
            'assigned_operator', 'created_by', 'reviewed_by', 'customer__city',
        ),
        pk=pk,
    )
    map_url = None
    if job.has_location:
        lat, lng = job.latitude, job.longitude
        map_url = f'https://www.openstreetmap.org/?mlat={lat}&mlon={lng}#map=17/{lat}/{lng}'
    return render(request, 'jobs/support_job_detail.html', {
        'job': job,
        'sections': review_sections(job),
        'map_url': map_url,
    })


@role_required(User.Role.ADMIN)
@require_POST
def support_job_review(request, pk):
    job = get_object_or_404(Job, pk=pk)
    try:
        job.mark_reviewed(request.user)
    except ValueError:
        messages.error(request, 'فقط کارهای ارسال‌شده قابل بررسی هستند.')
    else:
        messages.success(request, 'کار به‌عنوان بررسی‌شده ثبت شد.')
    return redirect('support_job_detail', pk=pk)




@role_required(User.Role.ADMIN)
@require_POST
def job_return(request, pk):
    job = get_object_or_404(Job, pk=pk)
    form = ReturnForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'دلیل برگشت کار را وارد کنید.')
        return redirect('support_job_detail', pk=pk)
    try:
        job.return_for_correction(request.user, form.cleaned_data['reason'])
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, 'کار برای اصلاح به تکنسین برگشت داده شد.')
    return redirect('support_job_detail', pk=pk)


@role_required(User.Role.ADMIN)
def photo_history(request):
    form = PhotoFilterForm(request.GET or None)
    media = (
        JobEvidence.objects.select_related(
            'job', 'job__assigned_operator', 'job__customer',
        )
        .order_by('-uploaded_at')
    )
    if form.is_valid():
        cd = form.cleaned_data
        if cd['job']:
            media = media.filter(job_id=cd['job'])
        if cd['kind']:
            media = media.filter(kind=cd['kind'])
        if cd['category']:
            media = media.filter(category=cd['category'])
        if cd['operator']:
            media = media.filter(job__assigned_operator=cd['operator'])
        if cd['date_from']:
            media = media.filter(uploaded_at__date__gte=cd['date_from'])
        if cd['date_to']:
            media = media.filter(uploaded_at__date__lte=cd['date_to'])

    page, qs = paginate(request, media, 24)
    return render(request, 'jobs/photo_history.html', {'form': form, 'page': page, 'qs': qs})




@role_required(User.Role.ADMIN)
def job_create(request):
    # Pre-select a customer when the link comes from a customer's page (?customer=<pk>)
    initial = {}
    if request.GET.get('customer'):
        initial['customer'] = request.GET['customer']

    form = JobCreateForm(request.POST or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        job = form.save(commit=False)
        job.created_by = request.user
        job.save()
        audit_log(
            request.user, AuditEntry.Action.JOB_CREATED, job,
            details=(
                f'تکنسین: {job.assigned_operator.get_full_name() or job.assigned_operator.username}'
                f' — مشترک: {job.customer.full_name}'
            ),
        )
        messages.success(request, f'کار شماره {job.pk} ایجاد و به تکنسین ارجاع شد.')
        return redirect('support_job_detail', pk=job.pk)

    # Tells the browser which workflows belong to each category (see the template script)
    workflow_map = {
        jt.value: [wf.value for wf in workflows_for_type]
        for jt, workflows_for_type in Job.VALID_WORKFLOWS.items()
    }
    return render(request, 'jobs/job_create.html', {
        'form': form, 'workflow_map': workflow_map,
    })





@role_required(User.Role.ADMIN)
def technician_report(request):
    form = ReportPeriodForm(request.GET or None)
    if form.is_valid() and 'export' in request.GET:
        date_from = form.cleaned_data['date_from']
        date_to = form.cleaned_data['date_to']
        workbook = build_report_workbook(collect_report(date_from, date_to), date_from, date_to)
        today = jdatetime.date.today().strftime('%Y-%m-%d')
        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename="technician-report-{today}.xlsx"'
        workbook.save(response)
        return response
    return render(request, 'jobs/technician_report.html', {'form': form})