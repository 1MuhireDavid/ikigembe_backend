from django.core.management.base import BaseCommand

from apps.movies.models import Movie
from apps.movies.transcoding import _transcode_worker


class Command(BaseCommand):
    help = 'Transcode a movie to HLS adaptive bitrate format using FFmpeg'

    def add_arguments(self, parser):
        parser.add_argument('--movie-id', type=int, help='ID of the movie to transcode')
        parser.add_argument('--all-pending', action='store_true', help='Transcode all not_started or failed movies')

    def handle(self, *args, **options):
        movie_id = options.get('movie_id')
        all_pending = options.get('all_pending')

        if movie_id:
            movies = Movie.objects.filter(id=movie_id)
            if not movies.exists():
                self.stderr.write(f'Movie with id={movie_id} not found.')
                return
        elif all_pending:
            movies = Movie.objects.filter(
                hls_status__in=['not_started', 'failed'],
                video_file__isnull=False,
            ).exclude(video_file='')
        else:
            self.stderr.write('Provide --movie-id <id> or --all-pending')
            return

        for m in movies:
            if not m.video_file:
                self.stdout.write(f'  Skipping movie {m.id} ({m.title}): no video file')
                continue
            self.stdout.write(f'Transcoding movie {m.id}: {m.title}...')
            _transcode_worker(m.id)  # runs synchronously so output is visible
            m.refresh_from_db()
            status_display = m.get_hls_status_display()
            if m.hls_status == 'ready':
                self.stdout.write(self.style.SUCCESS(f'  Done — status: {status_display}'))
            else:
                self.stdout.write(self.style.ERROR(f'  Failed — status: {status_display}: {m.hls_error_message}'))
