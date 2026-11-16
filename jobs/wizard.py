from django.urls import reverse

from . import workflows


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
    """Where the technician should go next: location first, then the current step."""
    if not job.has_location:
        return reverse('job_location', args=[job.pk])
    current = current_index(job)
    if current is None:
        return reverse('operator_home')
    return step_url(job, current)


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