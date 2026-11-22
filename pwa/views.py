from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse

from .icons import ALLOWED_SIZES, icon_png

THEME_COLOR = '#14305a'        # the dark blue of the site header (also the <meta name="theme-color">)
BACKGROUND_COLOR = '#f3f5f9'   # the page background of the default light theme (used on the splash screen)


def manifest(request):
    data = {
        'id': '/',
        'name': 'QGS',
        'short_name': 'QGS',                 # the label under the home-screen icon
        'description': 'سامانه کارهای میدانی QGS',
        'lang': 'fa',
        'dir': 'rtl',
        'start_url': '/',                    # "/" sends each user to the right home page, or to the login page
        'scope': '/',
        'display': 'standalone',             # opens without the browser's address bar
        'theme_color': THEME_COLOR,
        'background_color': BACKGROUND_COLOR,
        'icons': [
            {'src': reverse('pwa_icon', args=[192]), 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
            {'src': reverse('pwa_icon', args=[512]), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
            {'src': reverse('pwa_icon', args=[512]), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
        ],
    }
    response = JsonResponse(
        data,
        content_type='application/manifest+json',
        json_dumps_params={'ensure_ascii': False},
    )
    response['Cache-Control'] = 'no-cache'
    return response


def icon(request, size):
    if size not in ALLOWED_SIZES:
        raise Http404
    response = HttpResponse(icon_png(size), content_type='image/png')
    response['Cache-Control'] = 'public, max-age=86400'
    return response


def service_worker(request):
    # render_to_string (not render) on purpose: the browser re-checks this file very often, and
    # this way no context processors run, so no notification or database work happens for it.
    script = render_to_string('pwa/sw.js', {
        'version': getattr(settings, 'PWA_VERSION', '1'),
        'static_url': settings.STATIC_URL,
        'offline_url': reverse('pwa_offline'),
    })
    response = HttpResponse(script, content_type='application/javascript')
    response['Cache-Control'] = 'no-cache'      # the browser must always ask for the newest worker
    response['Service-Worker-Allowed'] = '/'
    return response


def offline(request):
    response = HttpResponse(render_to_string('pwa/offline.html'))
    response['Cache-Control'] = 'no-cache'
    return response


def install_help(request):
    return render(request, 'pwa/install.html')