from django.urls import reverse

from . import workflows
from .models import Job

def applicable_indexes(job):
    """Positions (in the workflow's full step list) of the steps that apply to this job."""
    return [i for i, step in enumerate(workflows.steps_for(job)) if step.applies_to(job)]


def current_index(job):
    """Position of the first unfinished applicable step, or None if everything is done."""
    steps = workflows.steps_for(job)
    for i in applicable_indexes(job):
        if not steps[i].is_complete(job):
            return i
    return None


def step_url(job, index):
    return reverse('job_step', args=[job.pk, index])


def next_url(job):
    """Where the technician should go next."""
    if not job.has_location:
        return reverse('job_location', args=[job.pk])
    current = current_index(job)
    if current is not None:
        return step_url(job, current)
    if job.status == Job.Status.RETURNED:
        # Everything is filled in, so go straight to the description to resubmit
        for i in applicable_indexes(job):
            if isinstance(workflows.steps_for(job)[i], workflows.DescriptionStep):
                return step_url(job, i)
    return reverse('operator_home')


def progress(job, active_index=None):
    """Data for the stepper bar: done / current / locked for each step."""
    steps = workflows.steps_for(job)
    current = current_index(job)
    items = [{
        'label': 'مکان',
        'state': 'done' if job.has_location else 'current',
        'active': False,
        'url': reverse('job_location', args=[job.pk]),
    }]
    for i in applicable_indexes(job):
        step = steps[i]
        if not job.has_location:
            state = 'locked'
        elif step.is_complete(job):
            state = 'done'
        elif i == current:
            state = 'current'
        else:
            state = 'locked'
        items.append({
            'label': step.key,
            'state': state,
            'active': i == active_index,
            'url': None if state == 'locked' else step_url(job, i),
        })
    return items






def step_sequence(job):
    """Addresses of every step in order: the location first, then the steps that apply to this job."""
    return [reverse('job_location', args=[job.pk])] + [
        step_url(job, i) for i in applicable_indexes(job)
    ]


def previous_url(job, current_path):
    """The address of the step before the one at current_path, or None on the first step."""
    urls = step_sequence(job)
    if current_path in urls:
        position = urls.index(current_path)
        if position > 0:
            return urls[position - 1]
    return None