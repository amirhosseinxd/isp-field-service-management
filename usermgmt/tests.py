from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from jobs.models import Job
from accounts.models import User
from audit.models import AuditEntry

PASSWORD = 'Pass-12345-xyz'
NEW_PASSWORD = 'Another-Pass-987'


def make_user(username, role=User.Role.OPERATOR, **extra):
    return User.objects.create_user(
        username=username, password=PASSWORD, role=role,
        first_name=extra.pop('first_name', username), last_name=extra.pop('last_name', 'تست'),
        **extra,
    )


class Base(TestCase):
    def setUp(self):
        self.owner = make_user('owner', User.Role.ADMIN, is_superuser=True)
        self.aide = make_user('aide', User.Role.ADMIN)
        self.tech = make_user('tech1')

    def edit_data(self, user, **extra):
        data = {'username': user.username, 'first_name': user.first_name, 'last_name': user.last_name, 'phone': ''}
        data.update(extra)
        return data
    def login(self, user):
        self.assertTrue(self.client.login(username=user.username, password=PASSWORD))

    def new_user_data(self, **extra):
        data = {
            'username': 'tech2', 'first_name': 'علی', 'last_name': 'رضایی', 'phone': '09120000000',
            'role': 'operator', 'password1': 'Strong-Pass-731', 'password2': 'Strong-Pass-731',
        }
        data.update(extra)
        return data


class AccessTests(Base):
    def test_technicians_cannot_open_the_user_pages(self):
        self.login(self.tech)
        for name, args in [('user_list', []), ('user_create', []), ('user_edit', [self.aide.pk])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 403)

    def test_anonymous_visitors_are_sent_to_login(self):
        self.assertEqual(self.client.get(reverse('user_list')).status_code, 302)


class CreateTests(Base):
    def test_support_creates_a_technician_with_a_hashed_password(self):
        self.login(self.aide)
        response = self.client.post(reverse('user_create'), self.new_user_data())
        self.assertRedirects(response, reverse('user_list'))
        user = User.objects.get(username='tech2')
        self.assertEqual(user.role, User.Role.OPERATOR)
        self.assertTrue(user.check_password('Strong-Pass-731'))
        self.assertNotIn('Strong-Pass-731', user.password)
        entry = AuditEntry.objects.get(action=AuditEntry.Action.USER_CREATED)
        self.assertEqual(entry.actor, self.aide)
        self.assertNotIn('Strong-Pass-731', entry.details)

    def test_ordinary_support_cannot_create_support_accounts(self):
        self.login(self.aide)
        response = self.client.get(reverse('user_create'))
        self.assertEqual([v for v, _ in response.context['form'].fields['role'].choices], ['operator'])
        response = self.client.post(reverse('user_create'), self.new_user_data(role='admin'))
        self.assertEqual(response.status_code, 200)       # form shown again with an error
        self.assertFalse(User.objects.filter(username='tech2').exists())

    def test_owner_creates_support_but_never_django_admin_powers(self):
        self.login(self.owner)
        self.client.post(reverse('user_create'), self.new_user_data(
            username='support2', role='admin', is_staff='on', is_superuser='on',
        ))
        user = User.objects.get(username='support2')
        self.assertEqual(user.role, User.Role.ADMIN)
        self.assertFalse(user.is_staff or user.is_superuser)

    def test_bad_passwords_and_duplicate_usernames_are_refused(self):
        self.login(self.aide)
        self.client.post(reverse('user_create'), self.new_user_data(password2='different'))
        self.client.post(reverse('user_create'), self.new_user_data(password1='12345678', password2='12345678'))
        self.client.post(reverse('user_create'), self.new_user_data(username='TECH1'))
        self.assertFalse(User.objects.filter(username='tech2').exists())
        self.assertEqual(User.objects.filter(username__iexact='tech1').count(), 1)


class EditTests(Base):
    def test_edit_changes_names_but_not_role_or_privileges(self):
        self.login(self.aide)
        self.client.post(reverse('user_edit', args=[self.tech.pk]), {
            'username': 'tech1', 'first_name': 'نام جدید', 'last_name': 'تست', 'phone': '',
            'role': 'admin', 'is_superuser': 'on',
        })
        self.tech.refresh_from_db()
        self.assertEqual(self.tech.first_name, 'نام جدید')
        self.assertEqual(self.tech.role, User.Role.OPERATOR)
        self.assertFalse(self.tech.is_superuser)
        self.assertTrue(AuditEntry.objects.filter(action=AuditEntry.Action.USER_UPDATED, actor=self.aide).exists())

    def test_own_username_is_locked_and_support_accounts_need_the_owner(self):
        self.login(self.aide)
        self.client.post(reverse('user_edit', args=[self.aide.pk]), {
            'username': 'changed', 'first_name': 'x', 'last_name': 'y', 'phone': '',
        })
        self.aide.refresh_from_db()
        self.assertEqual(self.aide.username, 'aide')
        self.assertEqual(self.aide.first_name, 'x')
        self.assertEqual(self.client.get(reverse('user_edit', args=[self.owner.pk])).status_code, 403)
        self.login(self.owner)
        self.assertEqual(self.client.get(reverse('user_edit', args=[self.aide.pk])).status_code, 200)


class ActivationTests(Base):
    def test_deactivate_and_activate_are_logged_and_keep_the_account(self):
        self.login(self.aide)
        url = reverse('user_set_active', args=[self.tech.pk])
        self.client.post(url, {'action': 'deactivate'})
        self.tech.refresh_from_db()
        self.assertFalse(self.tech.is_active)
        self.assertTrue(AuditEntry.objects.filter(action=AuditEntry.Action.USER_DEACTIVATED, actor=self.aide).exists())
        self.client.post(url, {'action': 'activate'})
        self.tech.refresh_from_db()
        self.assertTrue(self.tech.is_active)
        self.assertTrue(AuditEntry.objects.filter(action=AuditEntry.Action.USER_ACTIVATED, actor=self.aide).exists())

    def test_deactivation_closes_open_sessions_and_blocks_login(self):
        phone = self.client_class()
        self.assertTrue(phone.login(username='tech1', password=PASSWORD))
        self.assertEqual(phone.get(reverse('operator_home')).status_code, 200)
        self.login(self.aide)
        self.client.post(reverse('user_set_active', args=[self.tech.pk]), {'action': 'deactivate'})
        self.assertEqual(phone.get(reverse('operator_home')).status_code, 302)
        self.assertFalse(self.client_class().login(username='tech1', password=PASSWORD))

    def test_who_may_be_deactivated(self):
        self.login(self.aide)
        for target in (self.aide, self.owner):          # yourself, and a higher account
            response = self.client.post(reverse('user_set_active', args=[target.pk]), {'action': 'deactivate'})
            self.assertEqual(response.status_code, 403)
            target.refresh_from_db()
            self.assertTrue(target.is_active)
        self.login(self.owner)
        self.assertEqual(
            self.client.post(reverse('user_set_active', args=[self.owner.pk]), {'action': 'deactivate'}).status_code, 403)
        self.client.post(reverse('user_set_active', args=[self.aide.pk]), {'action': 'deactivate'})
        self.aide.refresh_from_db()
        self.assertFalse(self.aide.is_active)


class PasswordTests(Base):
    def test_reset_hashes_logs_without_the_password_and_closes_sessions(self):
        phone = self.client_class()
        phone.login(username='tech1', password=PASSWORD)
        self.login(self.aide)
        data = {'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD}
        response = self.client.post(reverse('user_set_password', args=[self.tech.pk]), data)
        self.assertRedirects(response, reverse('user_list'))
        self.tech.refresh_from_db()
        self.assertTrue(self.tech.check_password(NEW_PASSWORD))
        self.assertNotIn(NEW_PASSWORD, self.tech.password)
        entry = AuditEntry.objects.get(action=AuditEntry.Action.USER_PASSWORD_RESET)
        self.assertNotIn(NEW_PASSWORD, entry.details)
        self.assertEqual(phone.get(reverse('operator_home')).status_code, 302)

    def test_support_changes_own_password_and_stays_logged_in(self):
        self.login(self.aide)
        data = {'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD}
        self.client.post(reverse('user_set_password', args=[self.aide.pk]), data)
        self.assertEqual(self.client.get(reverse('user_list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('user_set_password', args=[self.owner.pk])).status_code, 403)


class ListTests(Base):
    def test_search_and_filters(self):
        make_user('zz_rezaei', first_name='علی', last_name='رضایی')
        gone = make_user('zz_karimi', first_name='حسن', last_name='کریمی')
        gone.is_active = False
        gone.save()
        self.login(self.aide)
        url = reverse('user_list')

        response = self.client.get(url, {'q': 'علی رضایی'})
        self.assertContains(response, 'zz_rezaei')
        self.assertNotContains(response, 'zz_karimi')

        response = self.client.get(url, {'role': 'admin'})
        self.assertContains(response, 'owner')
        self.assertNotContains(response, 'zz_rezaei')

        response = self.client.get(url, {'status': 'inactive'})
        self.assertContains(response, 'zz_karimi')
        self.assertNotContains(response, 'zz_rezaei')


class LastSeenTests(Base):
    def seen(self):
        return User.objects.get(pk=self.tech.pk).last_seen

    def test_activity_updates_last_seen_at_most_once_a_minute(self):
        self.login(self.tech)
        self.assertIsNone(self.seen())
        self.client.get(reverse('operator_home'))
        self.assertIsNotNone(self.seen())

        recent = timezone.now() - timedelta(seconds=10)
        User.objects.filter(pk=self.tech.pk).update(last_seen=recent)
        self.client.get(reverse('operator_home'))
        self.assertEqual(self.seen(), recent)                 # too soon: not rewritten

        older = timezone.now() - timedelta(minutes=3)
        User.objects.filter(pk=self.tech.pk).update(last_seen=older)
        self.client.get(reverse('operator_home'))
        self.assertGreater(self.seen(), older)

    def test_background_requests_do_not_count_as_activity(self):
        self.login(self.tech)
        self.client.get('/notifications/panel/')
        self.client.get('/sw.js')
        self.assertIsNone(self.seen())

    @override_settings(USER_ONLINE_MINUTES=5)
    def test_online_means_active_within_the_threshold(self):
        self.assertFalse(self.tech.is_online)                 # never seen
        self.tech.last_seen = timezone.now() - timedelta(minutes=2)
        self.assertTrue(self.tech.is_online)
        self.tech.last_seen = timezone.now() - timedelta(minutes=9)
        self.assertFalse(self.tech.is_online)



class AccountManagerTests(Base):
    def test_only_the_owner_can_grant_the_manager_checkbox(self):
        other = make_user('other', User.Role.ADMIN)
        self.login(self.aide)
        self.client.post(reverse('user_edit', args=[self.tech.pk]), self.edit_data(self.tech, can_manage_accounts='on'))
        self.tech.refresh_from_db()
        self.assertFalse(self.tech.can_manage_accounts)
        self.assertEqual(self.client.get(reverse('user_edit', args=[other.pk])).status_code, 403)

        self.login(self.owner)
        self.client.post(reverse('user_edit', args=[other.pk]), self.edit_data(other, role='admin', can_manage_accounts='on'))
        other.refresh_from_db()
        self.assertTrue(other.can_manage_accounts)
        self.assertTrue(AuditEntry.objects.filter(action=AuditEntry.Action.USER_ACCESS_CHANGED, actor=self.owner).exists())

    def test_a_manager_handles_support_accounts_but_not_other_managers_or_the_owner(self):
        manager = make_user('manager', User.Role.ADMIN, can_manage_accounts=True)
        peer = make_user('peer', User.Role.ADMIN, can_manage_accounts=True)
        plain = make_user('plain', User.Role.ADMIN)
        self.login(manager)

        self.client.post(reverse('user_create'), self.new_user_data(
            username='support3', role='admin', can_manage_accounts='on',
        ))
        created = User.objects.get(username='support3')
        self.assertEqual(created.role, User.Role.ADMIN)
        self.assertFalse(created.can_manage_accounts)          # a manager cannot hand out the checkbox

        self.assertEqual(self.client.get(reverse('user_edit', args=[plain.pk])).status_code, 200)
        self.client.post(reverse('user_set_active', args=[plain.pk]), {'action': 'deactivate'})
        plain.refresh_from_db()
        self.assertFalse(plain.is_active)

        for target in (peer, self.owner):
            self.assertEqual(self.client.get(reverse('user_edit', args=[target.pk])).status_code, 403)
            self.assertEqual(self.client.get(reverse('user_set_password', args=[target.pk])).status_code, 403)
            response = self.client.post(reverse('user_set_active', args=[target.pk]), {'action': 'deactivate'})
            self.assertEqual(response.status_code, 403)


class RoleChangeTests(Base):
    def test_the_role_field_exists_only_for_the_owner_editing_someone_else(self):
        other_owner = make_user('owner2', User.Role.ADMIN, is_superuser=True)
        self.login(self.aide)
        self.assertNotIn('role', self.client.get(reverse('user_edit', args=[self.tech.pk])).context['form'].fields)
        self.login(self.owner)
        self.assertIn('role', self.client.get(reverse('user_edit', args=[self.tech.pk])).context['form'].fields)
        for target in (self.owner, other_owner):           # yourself, and Django-admin accounts
            self.assertNotIn('role', self.client.get(reverse('user_edit', args=[target.pk])).context['form'].fields)

    def test_changing_a_role_needs_confirmation_and_is_logged(self):
        self.login(self.owner)
        url = reverse('user_edit', args=[self.tech.pk])
        self.client.post(url, self.edit_data(self.tech, role='admin'))                       # not confirmed
        self.tech.refresh_from_db()
        self.assertEqual(self.tech.role, User.Role.OPERATOR)
        self.client.post(url, self.edit_data(self.tech, role='admin', confirm_role_change='on'))
        self.tech.refresh_from_db()
        self.assertEqual(self.tech.role, User.Role.ADMIN)
        self.assertTrue(AuditEntry.objects.filter(action=AuditEntry.Action.USER_ROLE_CHANGED, actor=self.owner).exists())

    def test_demotion_removes_the_manager_checkbox(self):
        manager = make_user('manager', User.Role.ADMIN, can_manage_accounts=True)
        self.login(self.owner)
        self.client.post(reverse('user_edit', args=[manager.pk]), self.edit_data(
            manager, role='operator', can_manage_accounts='on', confirm_role_change='on',
        ))
        manager.refresh_from_db()
        self.assertEqual(manager.role, User.Role.OPERATOR)
        self.assertFalse(manager.can_manage_accounts)

    def test_a_technician_with_unfinished_jobs_cannot_become_support(self):
        # If Job.objects.create asks for another required field in your project, add it here
        Job.objects.create(
            job_type='malfunction_repair', workflow='malfunction',
            assigned_operator=self.tech, created_by=self.owner,
        )
        self.login(self.owner)
        self.client.post(reverse('user_edit', args=[self.tech.pk]), self.edit_data(
            self.tech, role='admin', confirm_role_change='on',
        ))
        self.tech.refresh_from_db()
        self.assertEqual(self.tech.role, User.Role.OPERATOR)

    def test_a_new_role_applies_on_the_very_next_click(self):
        phone = self.client_class()
        phone.login(username='tech1', password=PASSWORD)
        self.assertEqual(phone.get(reverse('operator_home')).status_code, 200)
        self.login(self.owner)
        self.client.post(reverse('user_edit', args=[self.tech.pk]), self.edit_data(
            self.tech, role='admin', confirm_role_change='on',
        ))
        self.assertEqual(phone.get(reverse('operator_home')).status_code, 403)
        self.assertEqual(phone.get(reverse('user_list')).status_code, 200)