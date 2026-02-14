from django.contrib import admin
from django.utils.html import format_html
from .models import Movie


@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    """
    Django Admin with file upload support
    Upload videos and images directly - no manual URL entry!
    """
    
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
            return format_html(
                '<img src="{}" width="50" height="75" style="object-fit: cover; border-radius: 4px;" />',
                obj.thumbnail.url
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
    class Media:
        css = {
            'all': ('admin/css/movie_admin.css',)
        }
        js = ('admin/js/movie_admin.js',)