from django.contrib import admin
from django.utils.html import format_html
from django import forms
from django.conf import settings
from .models import Movie
from .widgets import S3DirectUploadWidget


class MovieAdminForm(forms.ModelForm):
    video_file = forms.CharField(widget=S3DirectUploadWidget(), required=False)
    trailer_file = forms.CharField(widget=S3DirectUploadWidget(), required=False)
    thumbnail = forms.CharField(widget=S3DirectUploadWidget(), required=False)
    backdrop = forms.CharField(widget=S3DirectUploadWidget(), required=False)

    class Meta:
        model = Movie
        fields = '__all__'


@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    """
    Django Admin with file upload support
    Upload videos and images directly - no manual URL entry!
    """
    
    form = MovieAdminForm
    
    # Fields to display in list view
    list_display = [
        'id',
        'thumbnail_preview',
        'title',
        'price',
        'views',
        'rating',
        'release_date',
        'is_active',
        'has_free_preview',
        'created_at'
    ]
    
    # Filters
    list_filter = [
        'is_active',
        'has_free_preview',
        'release_date',
        'created_at',
        'rating'
    ]
    
    # Search
    search_fields = [
        'title',
        'overview'
    ]
    
    # Clickable links
    list_display_links = ['id', 'title']
    
    # Inline editable fields
    list_editable = [
        'price',
        'is_active',
        'has_free_preview'
    ]
    
    # Default ordering
    ordering = ['-created_at']
    
    # Items per page
    list_per_page = 25
    
    # Organize edit form
    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'overview')
        }),
        ('Cast & Crew', {
            'fields': ('cast', 'genres', 'producer'),
            'description': 'Cast is a list of actor names (JSON). Genres is a list of genre strings (JSON).'
        }),
        ('Upload Media Files', {
            'fields': (
                'thumbnail',
                'backdrop',
            ),
            'description': 'Upload movie poster and backdrop images'
        }),
        ('Upload Video Files', {
            'fields': (
                'video_file',
                'trailer_file',
            ),
            'description': 'Upload full movie and trailer video files'
        }),
        ('Video Details', {
            'fields': ('duration_minutes', 'trailer_duration_seconds')
        }),
        ('Pricing & Metrics', {
            'fields': ('price', 'views', 'rating')
        }),
        ('Status', {
            'fields': ('release_date', 'is_active', 'has_free_preview')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    # Read-only fields
    readonly_fields = ['created_at', 'updated_at']
    
    # Custom display methods
    def thumbnail_preview(self, obj):
        """Show thumbnail preview in list view"""
        if obj.thumbnail:
            # Build URL directly from the S3 key (obj.thumbnail.name)
            # to avoid MEDIA_URL prefix mismatch
            key = obj.thumbnail.name
            url = f'https://{settings.AWS_S3_CUSTOM_DOMAIN}/{key}'
            return format_html(
                '<img src="{}" width="50" height="75" style="object-fit: cover; border-radius: 4px;" />',
                url
            )
        return '-'
    thumbnail_preview.short_description = 'Poster'
    
    # Bulk actions
    actions = [
        'activate_movies',
        'deactivate_movies',
        'enable_free_preview',
        'disable_free_preview'
    ]
    
    @admin.action(description='Activate selected movies')
    def activate_movies(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} movie(s) activated successfully.')
    
    @admin.action(description='Deactivate selected movies')
    def deactivate_movies(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} movie(s) deactivated successfully.')
    
    @admin.action(description='Enable free preview')
    def enable_free_preview(self, request, queryset):
        updated = queryset.update(has_free_preview=True)
        self.message_user(request, f'Free preview enabled for {updated} movie(s).')
    
    @admin.action(description='Disable free preview')
    def disable_free_preview(self, request, queryset):
        updated = queryset.update(has_free_preview=False)
        self.message_user(request, f'Free preview disabled for {updated} movie(s).')
    
    # Add custom styling
    # Add custom styling
    class Media:
        # css = {
        #     'all': ('admin/css/movie_admin.css',)
        # }
        # js = ('admin/js/movie_admin.js',)
        pass

    def save_model(self, request, obj, form, change):
        """
        Handle direct S3 uploads.
        If a string is passed for a FileField (S3 key), we set it explicitly.
        """
        for field_name in ['video_file', 'trailer_file', 'thumbnail', 'backdrop']:
            field_data = form.cleaned_data.get(field_name)
            
            # If the data is a string (S3 Key), update the model field's name
            # If it's a File object, Django handles it normally (but our widget prevents this for large files)
            # If it's None/Empty, and we are not changing it, do nothing.
            
            if isinstance(field_data, str) and field_data:
                 # It's an S3 key string
                 getattr(obj, field_name).name = field_data
        
        super().save_model(request, obj, form, change)
