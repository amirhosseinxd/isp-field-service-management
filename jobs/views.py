
from django.contrib import messages
import mimetypes
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, F
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.models import User
from accounts.permissions import role_required

from .forms import JobFilterForm, LocationForm, PhotoFilterForm, PhotoForm, ReportForm
from .models import Job, JobPhoto




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
    blocked = guard_step(request, job, 'location')
    if blocked:
        return blocked
    return redirect(step_url(job, job.next_step()))


@role_required(User.Role.OPERATOR)
def job_location(request, pk):
    job = get_operator_job(request, pk)
    blocked = guard_step(request, job, 'location')
    if blocked:
        return blocked

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
        return redirect(step_url(job, job.next_step()))

    return render(request, 'jobs/step_location.html', {
        'job': job, 'form': form, 'steps': stepper(job, 'location'),
    })


@role_required(User.Role.OPERATOR)
def job_photos(request, pk, stage):
    if stage not in JobPhoto.Stage.values:
        raise Http404
    job = get_operator_job(request, pk)
    blocked = guard_step(request, job, stage)
    if blocked:
        return blocked

    form = PhotoForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        photo = form.save(commit=False)
        photo.job = job
        photo.stage = stage
        photo.uploaded_by = request.user
        photo.save()
        messages.success(request, 'عکس ثبت شد.')
        return redirect('job_photos', pk=job.pk, stage=stage)

    photos = job.photos.filter(stage=stage)
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



def paginate(request, queryset, per_page):
    page = Paginator(queryset, per_page).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return page, params.urlencode()


@login_required
def job_photo(request, pk):
    """Serve a photo file only to support admins and the job's own operator."""
    photo = get_object_or_404(JobPhoto.objects.select_related('job'), pk=pk)
    user = request.user
    allowed = user.role == User.Role.ADMIN or photo.job.assigned_operator_id == user.id
    if not allowed:
        raise Http404
    try:
        file = photo.image.open('rb')
    except FileNotFoundError:
        raise Http404
    content_type = mimetypes.guess_type(photo.image.name)[0] or 'application/octet-stream'
    response = FileResponse(file, content_type=content_type)
    response['Cache-Control'] = 'private, max-age=3600'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@role_required(User.Role.ADMIN)
def support_dashboard(request):
    # With no filters in the URL, show submitted jobs (the review queue)
    form = JobFilterForm(request.GET or {'status': Job.Status.SUBMITTED})
    jobs = (
        Job.objects.select_related('assigned_operator')
        .annotate(photo_total=Count('photos'))
        .order_by(F('submitted_at').desc(nulls_last=True), '-created_at')
    )
    if form.is_valid():
        cd = form.cleaned_data
        if cd['status']:
            jobs = jobs.filter(status=cd['status'])
        if cd['job_type']:
            jobs = jobs.filter(job_type=cd['job_type'])
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
    photo_groups = [
        (label, job.photos.filter(stage=value).select_related('uploaded_by'))
        for value, label in JobPhoto.Stage.choices
    ]
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
    photos = JobPhoto.objects.select_related('job', 'job__assigned_operator').order_by('-uploaded_at')
    if form.is_valid():
        cd = form.cleaned_data
        if cd['job']:
            photos = photos.filter(job_id=cd['job'])
        if cd['stage']:
            photos = photos.filter(stage=cd['stage'])
        if cd['operator']:
            photos = photos.filter(job__assigned_operator=cd['operator'])
        if cd['date_from']:
            photos = photos.filter(uploaded_at__date__gte=cd['date_from'])
        if cd['date_to']:
            photos = photos.filter(uploaded_at__date__lte=cd['date_to'])

    page, qs = paginate(request, photos, 24)
    return render(request, 'jobs/photo_history.html', {'form': form, 'page': page, 'qs': qs})