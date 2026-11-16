
from django.contrib import messages
import mimetypes
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, F
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.db import transaction
from inventory.models import Material
from accounts.models import User
from accounts.permissions import role_required

from . import wizard, workflows
from .forms import (
    MAX_PHOTOS_PER_STAGE, FtthOutcomeForm, JobFilterForm, LocationForm, MaterialsSelectionForm,
    PhotoFilterForm, PhotoForm, ReportForm, SpeedQuestionForm, VideoForm, YesNoQuestionForm,
)

from .models import Job, JobEvidence, JobMaterialUsage

import os
import re

from .forms import (
    MAX_PHOTOS_PER_STAGE, JobFilterForm, LocationForm, PhotoFilterForm, PhotoForm, ReportForm,
)


STEPS = [
    ('location', 'مکان'),
    ('before', 'قبل'),
    ('during', 'حین کار'),
    ('after', 'بعد'),
    ('report', 'گزارش'),
]
STEP_KEYS = [key for key, _ in STEPS]
CLOSED = (Job.Status.SUBMITTED, Job.Status.REVIEWED)


def step_url(job, key):
    if key == 'location':
        return reverse('job_location', args=[job.pk])
    if key == 'report':
        return reverse('job_report', args=[job.pk])
    return reverse('job_photos', args=[job.pk, key])


def stepper(job, active):
    """Progress bar data: done / current / locked for each step."""
    current_idx = STEP_KEYS.index(job.next_step())
    items = []
    for i, (key, label) in enumerate(STEPS):
        state = 'done' if i < current_idx else 'current' if i == current_idx else 'locked'
        items.append({
            'label': label,
            'state': state,
            'active': key == active,
            'url': None if state == 'locked' else step_url(job, key),
        })
    return items


def get_operator_job(request, pk):
    return get_object_or_404(Job, pk=pk, assigned_operator=request.user)


def guard_step(request, job, step):
    """Return a redirect if the job is closed or the step is locked, else None."""
    if job.status in CLOSED:
        messages.info(request, 'این کار قبلاً ارسال شده است.')
        return redirect('operator_home')
    current = job.next_step()
    if STEP_KEYS.index(step) > STEP_KEYS.index(current):
        messages.warning(request, 'ابتدا مرحله قبلی را کامل کنید.')
        return redirect(step_url(job, current))
    if job.status == Job.Status.ASSIGNED:
        job.status = Job.Status.IN_PROGRESS
        job.save(update_fields=['status'])
    return None


@role_required(User.Role.OPERATOR)
def operator_home(request):
    mine = Job.objects.filter(assigned_operator=request.user)
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
        form = ReportForm()
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




@role_required(User.Role.OPERATOR)
def job_photos(request, pk, stage):
    if stage not in JobEvidence.LEGACY_STAGES:
        raise Http404
    job = get_operator_job(request, pk)
    blocked = guard_step(request, job, stage)
    if blocked:
        return blocked

    form = PhotoForm(request.POST or None, request.FILES or None)
    photos = job.evidence.filter(kind=JobEvidence.Kind.PHOTO, category=stage)

    if request.method == 'POST' and form.is_valid():
        images = form.cleaned_data['images']
        if photos.count() + len(images) > MAX_PHOTOS_PER_STAGE:
            form.add_error('images', f'حداکثر {MAX_PHOTOS_PER_STAGE} عکس برای هر مرحله مجاز است.')
        else:
            for image in images:
                JobEvidence.objects.create(
                    job=job, kind=JobEvidence.Kind.PHOTO, category=stage,
                    file=image, uploaded_by=request.user,
                )
            messages.success(request, f'{len(images)} عکس ثبت شد.')
            return redirect('job_photos', pk=job.pk, stage=stage)

    next_key = STEP_KEYS[STEP_KEYS.index(stage) + 1]
    return render(request, 'jobs/step_photos.html', {
        'job': job,
        'form': form,
        'photos': photos,
        'stage_label': dict(STEPS)[stage],
        'can_continue': photos.exists(),
        'next_url': step_url(job, next_key),
        'steps': stepper(job, stage),
    })


@role_required(User.Role.OPERATOR)
def job_report(request, pk):
    job = get_operator_job(request, pk)
    blocked = guard_step(request, job, 'report')
    if blocked:
        return blocked

    form = ReportForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            job.submit(request.user, form.cleaned_data['description'])
        except (ValueError, PermissionError):
            messages.error(request, 'ارسال انجام نشد. مراحل ناقص است یا کار قبلاً ارسال شده.')
            return redirect('job_start', pk=job.pk)
        messages.success(request, 'کار با موفقیت ارسال شد.')
        return redirect('operator_home')

    return render(request, 'jobs/step_report.html', {
        'job': job, 'form': form, 'steps': stepper(job, 'report'),
    })

@role_required(User.Role.OPERATOR)
@require_POST
def job_photo_delete(request, pk, photo_pk):
    job = get_operator_job(request, pk)
    if job.status in CLOSED:
        messages.error(request, 'بعد از ارسال کار، حذف عکس ممکن نیست.')
        return redirect('operator_home')

    photo = get_object_or_404(JobEvidence, pk=photo_pk, job=job)
    stage = photo.category
    storage, name = photo.file.storage, photo.file.name
    photo.delete()          # database row first, so a failure can't leave a broken link
    storage.delete(name)    # then the file on disk
    messages.success(request, 'عکس حذف شد.')
    return redirect('job_photos', pk=job.pk, stage=stage)



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
        Job.objects.select_related('assigned_operator')
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
        Job.objects.select_related('assigned_operator', 'created_by', 'reviewed_by'),
        pk=pk,
    )
    report = getattr(job, 'report', None)
    photo_groups = []
    for value, label in JobEvidence.Category.choices:
        photos = job.evidence.filter(
            kind=JobEvidence.Kind.PHOTO, category=value,
        ).select_related('uploaded_by')
        if photos:
            photo_groups.append((label, photos))
    map_url = None
    if job.has_location:
        lat, lng = job.latitude, job.longitude
        map_url = f'https://www.openstreetmap.org/?mlat={lat}&mlon={lng}#map=17/{lat}/{lng}'
    return render(request, 'jobs/support_job_detail.html', {
        'job': job,
        'report': report,
        'photo_groups': photo_groups,
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
def photo_history(request):
    form = PhotoFilterForm(request.GET or None)
    photos = (
        JobEvidence.objects.filter(kind=JobEvidence.Kind.PHOTO)
        .select_related('job', 'job__assigned_operator')
        .order_by('-uploaded_at')
    )
    if form.is_valid():
        cd = form.cleaned_data
        if cd['job']:
            photos = photos.filter(job_id=cd['job'])
        if cd['category']:
            photos = photos.filter(category=cd['category'])
        if cd['operator']:
            photos = photos.filter(job__assigned_operator=cd['operator'])
        if cd['date_from']:
            photos = photos.filter(uploaded_at__date__gte=cd['date_from'])
        if cd['date_to']:
            photos = photos.filter(uploaded_at__date__lte=cd['date_to'])

    page, qs = paginate(request, photos, 24)
    return render(request, 'jobs/photo_history.html', {'form': form, 'page': page, 'qs': qs})