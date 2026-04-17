from django.db import migrations


def forward_migrate_subtitle_files(apps, schema_editor):
    """
    Copy existing Movie.subtitles_file S3 keys into the new Subtitle table
    as English default tracks. The S3 file is reused in-place — no re-upload.
    """
    Movie = apps.get_model('movies', 'Movie')
    Subtitle = apps.get_model('movies', 'Subtitle')
    migrated = 0
    for movie in Movie.objects.filter(subtitles_file__isnull=False).exclude(subtitles_file=''):
        if not Subtitle.objects.filter(movie=movie, language_code='en').exists():
            Subtitle.objects.create(
                movie=movie,
                language_code='en',
                language_name='English',
                subtitle_file=movie.subtitles_file.name,
                is_default=True,
                ordering=0,
            )
            migrated += 1
    if migrated:
        print(f'\n  Migrated {migrated} subtitle file(s) to the Subtitle model.')


def reverse_migrate_subtitle_files(apps, schema_editor):
    """
    On rollback, copy the English default subtitle S3 key back to Movie.subtitles_file.
    """
    Movie = apps.get_model('movies', 'Movie')
    Subtitle = apps.get_model('movies', 'Subtitle')
    for sub in Subtitle.objects.filter(language_code='en', is_default=True):
        movie = sub.movie
        movie.subtitles_file = sub.subtitle_file.name
        movie.save(update_fields=['subtitles_file'])


class Migration(migrations.Migration):

    dependencies = [
        ('movies', '0010_subtitle'),
    ]

    operations = [
        migrations.RunPython(
            forward_migrate_subtitle_files,
            reverse_migrate_subtitle_files,
        ),
    ]
