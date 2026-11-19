from django.test import TestCase
from django.urls import reverse

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