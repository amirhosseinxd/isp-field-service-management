from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts.models import User
from accounts.permissions import role_required

from .forms import LocationForm, PhotoForm, ReportForm
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