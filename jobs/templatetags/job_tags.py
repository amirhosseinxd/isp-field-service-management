from django import template

from .. import wizard

register = template.Library()


@register.simple_tag
def last_step_url(job):
    """Where the technician left off: the first unfinished step of this job."""
    return wizard.next_url(job)



@register.simple_tag
def previous_step_url(job, current_path):
    """The step before the one being viewed, or an empty string on the first step (the location)."""
    return wizard.previous_url(job, current_path) or ''