import io
import json

from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image


class PwaTests(TestCase):
    def test_manifest_describes_the_app_and_is_public(self):
        response = self.client.get('/manifest.webmanifest')   # no login on purpose
        self.assertEqual(response.status_code, 200)
        self.assertIn('manifest+json', response['Content-Type'])
        data = json.loads(response.content)
        self.assertEqual(data['name'], 'QGS')
        self.assertEqual(data['short_name'], 'QGS')
        self.assertEqual(data['display'], 'standalone')
        self.assertEqual(data['start_url'], '/')
        self.assertEqual(data['theme_color'], '#14305a')
        self.assertEqual(data['background_color'], '#f3f5f9')

    def test_manifest_icons_exist_and_have_the_declared_size(self):
        data = json.loads(self.client.get('/manifest.webmanifest').content)
        self.assertTrue({'192x192', '512x512'} <= {icon['sizes'] for icon in data['icons']})
        self.assertIn('maskable', {icon['purpose'] for icon in data['icons']})
        for icon in data['icons']:
            response = self.client.get(icon['src'])
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'image/png')
            width, height = Image.open(io.BytesIO(response.content)).size
            self.assertEqual(f'{width}x{height}', icon['sizes'])

    def test_apple_touch_icon_and_unknown_sizes(self):
        response = self.client.get(reverse('pwa_icon', args=[180]))
        self.assertEqual(Image.open(io.BytesIO(response.content)).size, (180, 180))
        self.assertEqual(self.client.get(reverse('pwa_icon', args=[100])).status_code, 404)

    @override_settings(PWA_VERSION='v7')
    def test_service_worker_is_versioned_and_only_handles_safe_requests(self):
        response = self.client.get('/sw.js')
        self.assertEqual(response.status_code, 200)
        self.assertIn('javascript', response['Content-Type'])
        self.assertEqual(response['Service-Worker-Allowed'], '/')
        self.assertIn('no-cache', response['Cache-Control'])
        body = response.content.decode()
        self.assertIn("var VERSION = 'v7';", body)
        self.assertIn("request.method !== 'GET'", body)        # forms and logins are never touched
        self.assertIn("addEventListener('fetch'", body)
        self.assertIn("addEventListener('push'", body)         # notifications keep working
        self.assertIn("addEventListener('notificationclick'", body)

    def test_offline_page_is_public_and_self_contained(self):
        response = self.client.get('/offline/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'اتصال اینترنت برقرار نیست')
        self.assertNotContains(response, 'http')              # nothing external, so it works with no connection

    def test_install_help_page_explains_the_ios_steps_in_persian(self):
        response = self.client.get('/install/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add to Home Screen')
        self.assertContains(response, 'Safari')
        self.assertContains(response, 'اشتراک‌گذاری')

    def test_every_page_links_the_manifest_and_ios_tags(self):
        response = self.client.get(reverse('login'))          # use your login URL name if different
        self.assertContains(response, 'rel="manifest"')
        self.assertContains(response, 'rel="apple-touch-icon"')
        self.assertContains(response, 'apple-mobile-web-app-capable')
        self.assertContains(response, 'id="install-banner"')