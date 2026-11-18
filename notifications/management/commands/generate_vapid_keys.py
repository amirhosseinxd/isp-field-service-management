from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from notifications.push import _derive_public_key, public_key_or_empty


class Command(BaseCommand):
    help = 'Create the key pair that signs browser push messages (once per installation).'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Replace an existing key.')

    def handle(self, *args, **options):
        path = Path(settings.VAPID_PRIVATE_KEY_FILE)
        if path.exists() and not options['force']:
            raise CommandError(
                f'{path} already exists. Replacing it makes every device subscribe again; '
                'use --force only if you really want that.'
            )
        key = ec.generate_private_key(ec.SECP256R1())
        path.write_bytes(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ))
        _derive_public_key.cache_clear()
        self.stdout.write(self.style.SUCCESS(f'Created {path}'))
        self.stdout.write(f'Public key: {public_key_or_empty()}')