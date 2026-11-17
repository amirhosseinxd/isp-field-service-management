from django.core.management.base import BaseCommand

from notifications.services import sync_overdue_notifications


class Command(BaseCommand):
    help = 'Create or retire the "customer waiting 14+ days" notifications for support staff.'

    def handle(self, *args, **options):
        count = sync_overdue_notifications()
        self.stdout.write(f'Jobs currently overdue: {count}')