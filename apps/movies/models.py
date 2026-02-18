from django.db import models
from django.core.validators import FileExtensionValidator


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