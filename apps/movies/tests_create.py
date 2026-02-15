from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.core.files.uploadedfile import SimpleUploadedFile
from .models import Movie
from datetime import date

class MovieCreateTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse('movie-create')
        
    def test_create_movie(self):
        # Create dummy files
        thumbnail = SimpleUploadedFile("thumb.jpg", b"file_content", content_type="image/jpeg")
        backdrop = SimpleUploadedFile("back.jpg", b"file_content", content_type="image/jpeg")
        video = SimpleUploadedFile("video.mp4", b"file_content", content_type="video/mp4")
        
        data = {
            'title': 'Test Movie',
            'overview': 'Test Overview',
            'thumbnail': thumbnail,
            'backdrop': backdrop,
            'video_file': video,
            'price': 1000,
            'release_date': date.today(),
            'duration_minutes': 120,
            'is_active': True
        }
        
        response = self.client.post(self.url, data, format='multipart')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Movie.objects.count(), 1)
        self.assertEqual(Movie.objects.get().title, 'Test Movie')
