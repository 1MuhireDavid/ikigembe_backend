from rest_framework import serializers
from apps.payments.models import Payment
from .models import Movie, WatchProgress


class MovieSerializer(serializers.ModelSerializer):
    """Basic movie serializer for list views"""

    thumbnail_url = serializers.SerializerMethodField()
    backdrop_url = serializers.SerializerMethodField()
    trailer_url = serializers.SerializerMethodField()
    video_url = serializers.SerializerMethodField()
    subtitles_url = serializers.SerializerMethodField()
    producer_profile = serializers.SerializerMethodField()

    class Meta:
        model = Movie
        fields = [
            'id',
            'title',
            'overview',
            'thumbnail_url',
            'backdrop_url',
            'trailer_url',
            'video_url',
            'subtitles_url',
            'price',
            'rating',
            'release_date',
            'views',
            'duration_minutes',
            'has_free_preview',
            'producer',
            'producer_profile',
        ]

    def get_thumbnail_url(self, obj):
        """Returns the absolute CloudFront/S3 URL for the thumbnail."""
        return obj.thumbnail.url if obj.thumbnail else None

    def get_backdrop_url(self, obj):
        """Returns the absolute CloudFront/S3 URL for the backdrop."""
        return obj.backdrop.url if obj.backdrop else None

    def get_trailer_url(self, obj):
        """Returns the trailer URL for background video autoplay (free, always accessible)."""
        return obj.trailer_file.url if obj.trailer_file else None

    def get_video_url(self, obj):
        """Returns the full video URL — for testing frontend playback."""
        return obj.video_file.url if obj.video_file else None

    def get_subtitles_url(self, obj):
        """Returns the URL for the subtitles file."""
        return obj.subtitles_file.url if obj.subtitles_file else None

    def get_producer_profile(self, obj):
        """Returns basic info about the linked producer user account."""
        user = obj.producer_profile
        if not user:
            return None
        return {
            'id': user.id,
            'name': user.full_name or obj.producer or '',
        }


class MovieDetailSerializer(serializers.ModelSerializer):
    """Detailed movie serializer - includes trailer info"""

    thumbnail_url = serializers.SerializerMethodField()
    backdrop_url = serializers.SerializerMethodField()
    trailer_url = serializers.SerializerMethodField()
    video_url = serializers.SerializerMethodField()
    subtitles_url = serializers.SerializerMethodField()
    producer_profile = serializers.SerializerMethodField()

    class Meta:
        model = Movie
        fields = [
            'id',
            'title',
            'overview',
            'thumbnail_url',
            'backdrop_url',
            'trailer_url',
            'trailer_duration_seconds',
            'video_url',
            'subtitles_url',
            'price',
            'views',
            'rating',
            'release_date',
            'duration_minutes',
            'has_free_preview',
            'is_active',
            'created_at',
            'cast',
            'genres',
            'producer',
            'producer_profile',
        ]

    def get_thumbnail_url(self, obj):
        return obj.thumbnail.url if obj.thumbnail else None

    def get_backdrop_url(self, obj):
        return obj.backdrop.url if obj.backdrop else None

    def get_trailer_url(self, obj):
        return obj.trailer_file.url if obj.trailer_file else None

    def get_video_url(self, obj):
        return obj.video_file.url if obj.video_file else None

    def get_subtitles_url(self, obj):
        return obj.subtitles_file.url if obj.subtitles_file else None

    def get_producer_profile(self, obj):
        user = obj.producer_profile
        if not user:
            return None
        return {
            'id': user.id,
            'name': user.full_name or obj.producer or '',
        }


class ProducerMovieListSerializer(serializers.ModelSerializer):
    """Read-only serializer for the producer's movie monitoring panel."""
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = Movie
        fields = [
            'id',
            'title',
            'overview',
            'thumbnail_url',
            'price',
            'views',
            'rating',
            'release_date',
            'duration_minutes',
            'is_active',
            'has_free_preview',
            'hls_status',
            'created_at',
            'genres',
        ]

    def get_thumbnail_url(self, obj):
        return obj.thumbnail.url if obj.thumbnail else None


class ProducerMovieDetailSerializer(serializers.ModelSerializer):
    """Full detail serializer for a producer viewing one of their own movies."""
    thumbnail_url = serializers.SerializerMethodField()
    backdrop_url = serializers.SerializerMethodField()
    trailer_url = serializers.SerializerMethodField()
    video_url = serializers.SerializerMethodField()
    hls_url = serializers.SerializerMethodField()

    class Meta:
        model = Movie
        fields = [
            'id',
            'title',
            'overview',
            'thumbnail_url',
            'backdrop_url',
            'trailer_url',
            'trailer_duration_seconds',
            'video_url',
            'hls_url',
            'hls_status',
            'price',
            'views',
            'rating',
            'release_date',
            'duration_minutes',
            'has_free_preview',
            'is_active',
            'cast',
            'genres',
            'producer',
            'created_at',
            'updated_at',
        ]

    def get_thumbnail_url(self, obj):
        return obj.thumbnail.url if obj.thumbnail else None

    def get_backdrop_url(self, obj):
        return obj.backdrop.url if obj.backdrop else None

    def get_trailer_url(self, obj):
        return obj.trailer_file.url if obj.trailer_file else None

    def get_video_url(self, obj):
        return obj.video_file.url if obj.video_file else None

    def get_hls_url(self, obj):
        return obj.hls_url


class MovieVideoAccessSerializer(serializers.ModelSerializer):
    """Full video access serializer"""

    video_url = serializers.SerializerMethodField()
    trailer_url = serializers.SerializerMethodField()
    subtitles_url = serializers.SerializerMethodField()
    access_granted = serializers.SerializerMethodField()
    hls_url = serializers.SerializerMethodField()

    class Meta:
        model = Movie
        fields = [
            'id',
            'title',
            'video_url',
            'trailer_url',
            'subtitles_url',
            'duration_minutes',
            'access_granted',
            'hls_status',
            'hls_url',
        ]

    def get_hls_url(self, obj):
        return obj.hls_url

    def get_video_url(self, obj):
        return obj.video_file.url if obj.video_file else None

    def get_trailer_url(self, obj):
        return obj.trailer_file.url if obj.trailer_file else None

    def get_subtitles_url(self, obj):
        return obj.subtitles_file.url if obj.subtitles_file else None

    def get_access_granted(self, obj):
        """Return True if the requesting user has a completed payment for this movie."""
        request = self.context.get('request')
        if request is None or not request.user.is_authenticated:
            return False
        return Payment.objects.filter(
            user=request.user,
            movie=obj,
            status='Completed',
        ).exists()


class MovieCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating movies with file uploads"""

    class Meta:
        model = Movie
        fields = [
            'id',
            'title',
            'overview',
            'thumbnail',
            'backdrop',
            'video_file',
            'trailer_file',
            'subtitles_file',
            'price',
            'release_date',
            'duration_minutes',
            'trailer_duration_seconds',
            'is_active',
            'has_free_preview',
            'cast',
            'genres',
            'producer',
            'producer_profile'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'views', 'rating']


class WatchProgressSerializer(serializers.ModelSerializer):
    """Read/write serializer for a user's playback position on a movie."""

    class Meta:
        model = WatchProgress
        fields = ['movie', 'progress_seconds', 'duration_seconds', 'completed', 'last_watched_at']
        read_only_fields = ['last_watched_at']

    def validate(self, attrs):
        duration = attrs.get('duration_seconds', 0)
        progress = attrs.get('progress_seconds', 0)
        if duration and progress > duration:
            raise serializers.ValidationError(
                {'progress_seconds': 'progress_seconds cannot exceed duration_seconds.'}
            )
        return attrs


class MyListMovieSerializer(serializers.ModelSerializer):
    """
    Movie card shown in "My List" and "Continue Watching".
    Includes watch-progress fields when a WatchProgress object is annotated
    onto the instance as ``watch_progress_obj``.
    """
    thumbnail_url = serializers.SerializerMethodField()
    progress_seconds = serializers.SerializerMethodField()
    duration_seconds = serializers.SerializerMethodField()
    completed = serializers.SerializerMethodField()
    last_watched_at = serializers.SerializerMethodField()

    class Meta:
        model = Movie
        fields = [
            'id', 'title', 'overview', 'thumbnail_url',
            'duration_minutes', 'genres', 'rating', 'price',
            'progress_seconds', 'duration_seconds', 'completed', 'last_watched_at',
        ]

    def get_thumbnail_url(self, obj):
        return obj.thumbnail.url if obj.thumbnail else None

    def _progress(self, obj):
        return getattr(obj, 'watch_progress_obj', None)

    def get_progress_seconds(self, obj):
        p = self._progress(obj)
        return p.progress_seconds if p else 0

    def get_duration_seconds(self, obj):
        p = self._progress(obj)
        return p.duration_seconds if p else 0

    def get_completed(self, obj):
        p = self._progress(obj)
        return p.completed if p else False

    def get_last_watched_at(self, obj):
        p = self._progress(obj)
        return p.last_watched_at if p else None
