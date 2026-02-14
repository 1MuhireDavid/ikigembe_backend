from rest_framework import serializers
from .models import Movie


class MovieSerializer(serializers.ModelSerializer):
    """Basic movie serializer for list views"""
    
    # These will automatically return the full URLs
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
        """Get full URL for thumbnail"""
        if obj.thumbnail:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.thumbnail.url)
            return obj.thumbnail.url
        return None
    
    def get_backdrop_url(self, obj):
        """Get full URL for backdrop"""
        if obj.backdrop:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.backdrop.url)
            return obj.backdrop.url
        return None


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
            'created_at'
        ]
    
    def get_thumbnail_url(self, obj):
        if obj.thumbnail:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.thumbnail.url)
            return obj.thumbnail.url
        return None
    
    def get_backdrop_url(self, obj):
        if obj.backdrop:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.backdrop.url)
            return obj.backdrop.url
        return None
    
    def get_trailer_url(self, obj):
        if obj.trailer_file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.trailer_file.url)
            return obj.trailer_file.url
        return None


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
        if obj.video_file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.video_file.url)
            return obj.video_file.url
        return None
    
    def get_trailer_url(self, obj):
        if obj.trailer_file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.trailer_file.url)
            return obj.trailer_file.url
        return None
    
    def get_access_granted(self, obj):
        """
        Check if user has paid for this movie
        For now, returns True for development
        """
        # TODO: Implement payment verification
        return True