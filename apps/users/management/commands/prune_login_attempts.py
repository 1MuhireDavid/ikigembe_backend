from django.core.management.base import BaseCommand
from apps.users.models import FailedLoginAttempt


class Command(BaseCommand):
    help = 'Delete expired FailedLoginAttempt rows (older than the lockout window).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--window',
            type=int,
            default=15,
            help='Lockout window in minutes (default: 15). Rows older than this are deleted.',
        )

    def handle(self, *args, **options):
        window = options['window']
        deleted = FailedLoginAttempt.prune_expired(window_minutes=window)
        self.stdout.write(
            self.style.SUCCESS(f'Deleted {deleted} expired FailedLoginAttempt row(s) (window={window}m).')
        )
