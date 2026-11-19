from django import template

register = template.Library()


@register.simple_tag
def nav_active(request, *url_names):
    """Returns 'active' when the page being shown belongs to one of these named addresses."""
    match = getattr(request, 'resolver_match', None)
    return 'active' if match and match.url_name in url_names else ''