from django.db import models, transaction
from django.core.validators import FileExtensionValidator
from django.conf import settings


LANGUAGE_CHOICES = [
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
]


def _subtitle_upload_path(instance, filename):
    import os
    import uuid
    ext = os.path.splitext(filename)[1]
    return f'movies/subtitles/{instance.movie_id}/{uuid.uuid4()}{ext}'


class Movie(models.Model):
    """
    Movie model with direct file uploads
    Videos and images are uploaded directly, not via manual URLs
    """
    
    # Basic Information
    title = models.CharField(max_length=255)
    overview = models.TextField()
    
    # Media Files (uploaded directly)
    thumbnail = models.ImageField(
        upload_to='movies/thumbnails/',
        null=True,
        help_text='Upload movie poster/thumbnail (recommended: 300x450px)'
        
    )
    backdrop = models.ImageField(
        upload_to='movies/backdrops/',
        blank=True,
        null=True,
        help_text='Upload backdrop image (recommended: 1280x720px)'
    )
    
    # Video Files
    video_file = models.FileField(
        upload_to='movies/full/',
        validators=[FileExtensionValidator(allowed_extensions=['mp4', 'mov', 'avi', 'mkv'])],
        help_text='Upload full movie video file',
        null=True
    )
    trailer_file = models.FileField(
        upload_to='movies/trailers/',
        validators=[FileExtensionValidator(allowed_extensions=['mp4', 'mov', 'avi', 'mkv'])],
        blank=True,
        null=True,
        help_text='Upload trailer video file (optional)'
    )
    subtitles_file = models.FileField(
        upload_to='movies/subtitles/',
        validators=[FileExtensionValidator(allowed_extensions=['vtt', 'srt'])],
        blank=True,
        null=True,
        help_text='Upload subtitles file in VTT or SRT format (optional)'
    )
    
    # Cast, Genres, Producer
    cast = models.JSONField(
        default=list,
        blank=True,
        help_text='List of actor names, e.g. ["Actor One", "Actor Two"]'
    )
    genres = models.JSONField(
        default=list,
        blank=True,
        help_text='List of genres, e.g. ["Action", "Drama"]'
    )
    producer = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text='Name of the movie producer'
    )
    producer_profile = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uploaded_movies',
        limit_choices_to={'role': 'Producer'},
        help_text='Producer User Account'
    )
    
    # Video Metadata
    duration_minutes = models.PositiveIntegerField(
        default=0,
        help_text='Duration in minutes'
    )
    trailer_duration_seconds = models.PositiveIntegerField(
        default=0,
        help_text='Trailer duration in seconds',
        null=True
    )
    
    # Pricing and Metrics
    price = models.PositiveIntegerField(
        null=True,
        default=500,
        help_text='Price in RWF'
    )
    views = models.PositiveIntegerField(default=0)
    rating = models.FloatField(default=0.0)
    
    # HLS Adaptive Bitrate Streaming
    HLS_STATUS_CHOICES = [
        ('not_started', 'Not Started'),
        ('processing',  'Processing'),
        ('ready',       'Ready'),
        ('failed',      'Failed'),
    ]
    hls_status = models.CharField(
        max_length=20,
        choices=HLS_STATUS_CHOICES,
        default='not_started',
        db_index=True,
    )
    hls_master_key = models.CharField(max_length=500, blank=True, null=True)
    hls_error_message = models.TextField(blank=True, null=True)
    hls_started_at = models.DateTimeField(null=True, blank=True)
    hls_completed_at = models.DateTimeField(null=True, blank=True)

    # Status
    release_date = models.DateField()
    is_active = models.BooleanField(default=True)
    has_free_preview = models.BooleanField(
        default=True,
        null=True,
        help_text='Allow users to watch trailer for free'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Movie'
        verbose_name_plural = 'Movies'

    def __str__(self):
        return self.title
    
    def increment_views(self):
        """Increment view count when video is watched"""
        self.views += 1
        self.save(update_fields=['views'])
    
    @property
    def thumbnail_url(self):
        """Get full URL for thumbnail"""
        return self.thumbnail.url if self.thumbnail else None
    
    @property
    def backdrop_url(self):
        """Get full URL for backdrop"""
        return self.backdrop.url if self.backdrop else None
    
    @property
    def video_url(self):
        """Get full URL for video file"""
        return self.video_file.url if self.video_file else None
    
    @property
    def trailer_url(self):
        """Get full URL for trailer file"""
        return self.trailer_file.url if self.trailer_file else None

    @property
    def hls_url(self):
        """Get full CloudFront URL for HLS master playlist"""
        if self.hls_status == 'ready' and self.hls_master_key:
            return f"https://{settings.AWS_S3_CUSTOM_DOMAIN}/{self.hls_master_key}"
        return None


class Subtitle(models.Model):
    """
    A single subtitle track for a movie in a specific language.
    A movie can have one track per language_code.
    """
    movie = models.ForeignKey(
        Movie,
        on_delete=models.CASCADE,
        related_name='subtitles',
    )
    language_code = models.CharField(
        max_length=10,
        choices=LANGUAGE_CHOICES,
        help_text='ISO 639-1 language code, e.g. "en", "fr", "rw"',
    )
    language_name = models.CharField(
        max_length=100,
        help_text='Human-readable name — auto-populated from language_code if blank.',
    )
    subtitle_file = models.FileField(
        upload_to=_subtitle_upload_path,
        validators=[FileExtensionValidator(allowed_extensions=['vtt', 'srt'])],
        help_text='Subtitle file in VTT or SRT format',
    )
    is_default = models.BooleanField(
        default=False,
        help_text='Pre-selected track in the player',
    )
    ordering = models.PositiveSmallIntegerField(
        default=0,
        help_text='Display order in the subtitle track selector',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['ordering', 'language_code']
        unique_together = [('movie', 'language_code')]
        verbose_name = 'Subtitle'
        verbose_name_plural = 'Subtitles'

    def __str__(self):
        return f'{self.movie.title} — {self.language_name} ({self.language_code})'

    def save(self, *args, **kwargs):
        if not self.language_name:
            self.language_name = dict(LANGUAGE_CHOICES).get(self.language_code, self.language_code)
        with transaction.atomic():
            if self.is_default:
                # Lock all existing subtitle rows for this movie so concurrent
                # writes cannot interleave the default-unsetting and the save.
                list(Subtitle.objects.select_for_update().filter(movie_id=self.movie_id))
                Subtitle.objects.filter(
                    movie_id=self.movie_id, is_default=True
                ).exclude(pk=self.pk).update(is_default=False)
            super().save(*args, **kwargs)


class WatchProgress(models.Model):
    """
    Tracks how far a user has watched a movie, enabling "Continue Watching".
    One record per (user, movie) pair — updated in place on each progress save.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='watch_progress',
    )
    movie = models.ForeignKey(
        Movie,
        on_delete=models.CASCADE,
        related_name='watch_progress',
    )
    # Playback position in seconds from the start of the movie.
    progress_seconds = models.PositiveIntegerField(default=0)
    # Total duration in seconds — stored here so the frontend doesn't need a
    # second request to calculate the completion percentage.
    duration_seconds = models.PositiveIntegerField(default=0)
    completed = models.BooleanField(default=False)
    last_watched_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'movie')
        ordering = ['-last_watched_at']

    def __str__(self):
        return f'{self.user} → {self.movie.title} ({self.progress_seconds}s)'