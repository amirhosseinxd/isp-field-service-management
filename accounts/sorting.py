from django.db.models import F


def read_sort(request, allowed, default):
    """Which column to sort by and in which direction, taken from ?sort=...&dir=..."""
    key = request.GET.get('sort')
    if key not in allowed:
        key = default
    direction = 'asc' if request.GET.get('dir') == 'asc' else 'desc'
    return key, direction


def order_by_field(field_name, direction):
    """An ordering that puts empty values last, whichever way you sort."""
    field = F(field_name)
    return field.asc(nulls_last=True) if direction == 'asc' else field.desc(nulls_last=True)


def header_links(request, keys, active_key, active_direction):
    """For each sortable column: the address that sorts by it, and which arrow to draw."""
    base = request.GET.copy()
    base.pop('page', None)             # a new order starts from the first page
    links = {}
    for key in keys:
        params = base.copy()
        params['sort'] = key
        if key == active_key:
            params['dir'] = 'asc' if active_direction == 'desc' else 'desc'   # clicking flips the order
            arrow = 'down' if active_direction == 'desc' else 'up'
        else:
            params['dir'] = 'desc'                                            # newest first to start
            arrow = 'down'
        links[key] = {'url': '?' + params.urlencode(), 'arrow': arrow, 'active': key == active_key}
    return links