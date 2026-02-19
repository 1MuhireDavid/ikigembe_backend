from rest_framework import serializers
from .models import Movie


class MovieSerializer(serializers.ModelSerializer):
    """Basic movie serializer for list views"""

    # FileField.url already returns a full https:// S3/CloudFront URL
    thumbnail_url = serializers.SerializerMethodField()
    backdrop_url = serializers.SerializerMethodField()

    class Meta:
        model = Movie
        fields = [
            'id',
            'title',
            'overview',
            'thumbnail_url',
            'backdrop_url',
            'price',
            'rating',
            'release_date',
            'views',
            'duration_minutes',
            'has_free_preview'
        ]

    def get_thumbnail_url(self, obj):
        """Returns the absolute CloudFront/S3 URL for the thumbnail."""
        return obj.thumbnail.url if obj.thumbnail else None

    def get_backdrop_url(self, obj):
        """Returns the absolute CloudFront/S3 URL for the backdrop."""
        return obj.backdrop.url if obj.backdrop else None


class MovieDetailSerializer(serializers.ModelSerializer):
    """Detailed movie serializer - includes trailer info"""

    thumbnail_url = serializers.SerializerMethodField()
    backdrop_url = serializers.SerializerMethodField()
    trailer_url = serializers.SerializerMethodField()

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
            'producer'
        ]

    def get_thumbnail_url(self, obj):
        return obj.thumbnail.url if obj.thumbnail else None

    def get_backdrop_url(self, obj):
        return obj.backdrop.url if obj.backdrop else None

    def get_trailer_url(self, obj):
        return obj.trailer_file.url if obj.trailer_file else None


class MovieVideoAccessSerializer(serializers.ModelSerializer):
    """Full video access serializer"""

    video_url = serializers.SerializerMethodField()
    trailer_url = serializers.SerializerMethodField()
    access_granted = serializers.SerializerMethodField()

    class Meta:
        model = Movie
        fields = [
            'id',
            'title',
            'video_url',
            'trailer_url',
            'duration_minutes',
            'access_granted'
        ]

    def get_video_url(self, obj):
        return obj.video_file.url if obj.video_file else None

    def get_trailer_url(self, obj):
        return obj.trailer_file.url if obj.trailer_file else None

    def get_access_granted(self, obj):
        """
        Check if user has paid for this movie.
        For now, returns True for development.
        """
        # TODO: Implement payment verification
        return True


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
            'price',
            'release_date',
            'duration_minutes',
            'trailer_duration_seconds',
            'is_active',
            'has_free_preview',
            'cast',
            'genres',
            'producer'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'views', 'rating']
