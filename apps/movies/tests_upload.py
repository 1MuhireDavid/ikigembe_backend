from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth.models import User
from unittest.mock import patch, MagicMock

class PresignedURLTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse('presigned-url')
        self.admin_user = User.objects.create_superuser('admin', 'admin@example.com', 'password123')
        self.client.force_authenticate(user=self.admin_user)

    @patch('boto3.client')
    def test_get_presigned_url(self, mock_boto_client):
        # Mock S3 client response
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3
        mock_s3.generate_presigned_post.return_value = {
            'url': 'https://s3.amazonaws.com/bucket',
            'fields': {'key': 'value'}
        }

        # Test valid request
        response = self.client.get(self.url, {'file_name': 'test.mp4', 'file_type': 'video/mp4'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('url', response.data)
        self.assertIn('fields', response.data)
        self.assertIn('file_key', response.data)
        
        # Verify S3 client was called correctly
        mock_s3.generate_presigned_post.assert_called_once()
        
    def test_missing_params(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
