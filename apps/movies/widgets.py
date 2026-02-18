from django import forms
from django.conf import settings

class S3DirectUploadWidget(forms.TextInput):
    template_name = 'movies/widgets/s3_direct_upload.html'
    
    def __init__(self, attrs=None):
        default_attrs = {
            'class': 's3-direct-upload',
            'data-bucket': settings.AWS_STORAGE_BUCKET_NAME,
            'data-region': settings.AWS_S3_REGION_NAME,
            'data-max-size': settings.FILE_UPLOAD_MAX_MEMORY_SIZE,
        }
        if attrs:
            default_attrs.update(attrs)
        super().__init__(default_attrs)

    class Media:
        js = ('movies/js/s3_upload.js',)
        css = {
            'all': ('movies/css/s3_upload.css',)
        }
