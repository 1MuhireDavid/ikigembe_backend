from django.db import migrations, models
import apps.movies.models
import django.core.validators
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('movies', '0009_watchprogress'),
    ]

    operations = [
        migrations.CreateModel(
            name='Subtitle',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('language_code', models.CharField(
                    choices=[
                        ('en', 'English'),
                        ('fr', 'French'),
                        ('rw', 'Kinyarwanda'),
                        ('sw', 'Swahili'),
                        ('ar', 'Arabic'),
                        ('es', 'Spanish'),
                        ('pt', 'Portuguese'),
                        ('zh', 'Chinese'),
                        ('de', 'German'),
                        ('it', 'Italian'),
                    ],
                    help_text='ISO 639-1 language code, e.g. "en", "fr", "rw"',
                    max_length=10,
                )),
                ('language_name', models.CharField(
                    help_text='Human-readable name — auto-populated from language_code if blank.',
                    max_length=100,
                )),
                ('subtitle_file', models.FileField(
                    help_text='Subtitle file in VTT or SRT format',
                    upload_to=apps.movies.models._subtitle_upload_path,
                    validators=[django.core.validators.FileExtensionValidator(allowed_extensions=['vtt', 'srt'])],
                )),
                ('is_default', models.BooleanField(
                    default=False,
                    help_text='Pre-selected track in the player',
                )),
                ('ordering', models.PositiveSmallIntegerField(
                    default=0,
                    help_text='Display order in the subtitle track selector',
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('movie', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='subtitles',
                    to='movies.movie',
                )),
            ],
            options={
                'verbose_name': 'Subtitle',
                'verbose_name_plural': 'Subtitles',
                'ordering': ['ordering', 'language_code'],
                'unique_together': {('movie', 'language_code')},
            },
        ),
    ]
