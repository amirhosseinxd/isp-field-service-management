from django.test import TestCase
from django.urls import reverse

from jobs.models import Job

from .models import User

PASSWORD = 'pw-12345-test'


class HeaderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User.objects.create_user(username='h_admin', password=PASSWORD, role=User.Role.ADMIN)
        User.objects.create_user(username='h_tech', password=PASSWORD, role=User.Role.OPERATOR)

    def test_support_menu_highlights_the_current_section(self):
        self.client.login(username='h_admin', password=PASSWORD)
        page = self.client.get(reverse('customer_list'))
        self.assertContains(page, f'href="{reverse("customer_list")}" class="active"')
        self.assertNotContains(page, f'href="{reverse("audit_list")}" class="active"')

    def test_technicians_see_the_app_name_but_no_support_menu(self):
        self.client.login(username='h_tech', password=PASSWORD)
        page = self.client.get(reverse('operator_home'))
        self.assertContains(page, 'class="brand"')
        self.assertNotContains(page, reverse('audit_list'))



    def test_there_is_exactly_one_bell_in_the_header(self):
        self.client.login(username='h_tech', password=PASSWORD)
        page = self.client.get(reverse('operator_home')).content.decode()
        self.assertEqual(page.count('id="bell"'), 1)


class LookTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username='l_admin', password=PASSWORD, role=User.Role.ADMIN)
        cls.tech = User.objects.create_user(username='l_tech', password=PASSWORD, role=User.Role.OPERATOR)

    def test_status_badges_are_coloured_by_status(self):
        Job.objects.create(
            job_type='installation', workflow='fusion',
            assigned_operator=self.tech, created_by=self.admin,
        )
        self.client.login(username='l_tech', password=PASSWORD)
        self.assertContains(self.client.get(reverse('operator_home')), 'badge status-assigned')
        self.client.logout()

        self.client.login(username='l_admin', password=PASSWORD)
        page = self.client.get(reverse('support_dashboard'), {'status': ''})
        self.assertContains(page, 'badge status-assigned')

    def test_an_empty_job_list_shows_an_empty_state(self):
        self.client.login(username='l_tech', password=PASSWORD)
        self.assertContains(self.client.get(reverse('operator_home')), 'empty-state')

    def test_login_page_is_centered_and_has_the_theme_button(self):
        page = self.client.get(reverse('login'))
        self.assertContains(page, 'auth-page')
        self.assertContains(page, 'theme-btn')
        self.assertContains(page, 'data-theme="plain"')   # light theme is the default



class ThemeAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User.objects.create_user(username='t1_admin', password=PASSWORD, role=User.Role.ADMIN)
        User.objects.create_user(username='t1_tech', password=PASSWORD, role=User.Role.OPERATOR)

    def test_the_image_theme_is_offered_to_support_staff_only(self):
        self.client.login(username='t1_admin', password=PASSWORD)
        self.assertContains(self.client.get(reverse('customer_list')), 'data-themes="plain dark image"')
        self.client.logout()

        self.client.login(username='t1_tech', password=PASSWORD)
        page = self.client.get(reverse('operator_home'))
        self.assertContains(page, 'data-themes="plain dark"')
        self.assertNotContains(page, 'plain dark image')

    def test_the_login_page_offers_light_and_dark_only(self):
        self.assertContains(self.client.get(reverse('login')), 'data-themes="plain dark"')