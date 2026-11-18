from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from notifications.push import send_to_user


class Command(BaseCommand):
    help = 'Send a test browser push to every device of one user.'

    def add_arguments(self, parser):
        parser.add_argument('username')

    def handle(self, *args, **options):
        user = User.objects.filter(username=options['username']).first()
        if user is None:
            raise CommandError('No such user.')
        devices = user.push_subscriptions.count()
        delivered = send_to_user(user, {
            'title': 'آزمایش اعلان',
            'body': 'اگر این پیام را می‌بینید، اعلان مرورگر درست کار می‌کند.',
            'url': '/',
            'tag': 'push-test',
        })
        self.stdout.write(f'Devices: {devices}, accepted by the push service: {delivered}')