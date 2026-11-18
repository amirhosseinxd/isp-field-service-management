from django import template

from .. import wizard

register = template.Library()


@register.simple_tag
def last_step_url(job):
    """Where the technician left off: the first unfinished step of this job."""
    return wizard.next_url(job)