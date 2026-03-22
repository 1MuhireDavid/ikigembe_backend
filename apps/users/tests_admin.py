from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from apps.movies.models import Movie
from apps.payments.models import Payment, WithdrawalRequest

User = get_user_model()


class AdminDashboardTests(APITestCase):

    def setUp(self):
        # Create users
        self.admin = User.objects.create_user(
            email='admin@example.com',
            password='Password123!',
            first_name='Admin',
            last_name='User',
            role='Admin',
            is_staff=True
        )
        
        self.producer = User.objects.create_user(
            email='producer@example.com',
            password='Password123!',
            first_name='Producer',
            last_name='User',
            role='Producer'
        )
        
        self.viewer1 = User.objects.create_user(
            email='viewer1@example.com',
            password='Password123!',
            first_name='Viewer',
            last_name='One',
            role='Viewer'
        )
        self.viewer2 = User.objects.create_user(
            email='viewer2@example.com',
            password='Password123!',
            first_name='Viewer',
            last_name='Two',
            role='Viewer'
        )

        # Create movies
        self.movie1 = Movie.objects.create(
            title='Movie 1',
            overview='Test',
            price=1000,
            release_date=timezone.now().date(),
            producer_profile=self.producer,
            views=15
        )
        self.movie2 = Movie.objects.create(
            title='Movie 2',
            overview='Test 2',
            price=2000,
            release_date=timezone.now().date(),
            producer_profile=self.producer,
            views=10
        )

        # Create payments
        self.payment1 = Payment.objects.create(
            user=self.viewer1,
            movie=self.movie1,
            amount=1000,
            status='Completed'
        )
        self.payment2 = Payment.objects.create(
            user=self.viewer2,
            movie=self.movie2,
            amount=2000,
            status='Completed'
        )
        self.payment3 = Payment.objects.create(
            user=self.viewer1,
            movie=self.movie2,
            amount=2000,
            status='Failed' # Unsuccessful payment
        )

        # Total revenue = 3000
        # Producer earnings = 2100
        # Ikigembe commission = 900
        
        # Withdrawals
        WithdrawalRequest.objects.create(
            producer=self.producer,
            amount=1000,
            status='Approved'
        )
        
        # Auth Token
        reg_url = '/api/auth/register/'
        self.client.post(reg_url, {
            'email': 'admintemp@example.com',
            'password': 'StrongPass1!',
            'password_confirm': 'StrongPass1!',
            'role': 'Admin'
        })
        login_resp = self.client.post('/api/auth/login/', {
            'identifier': 'admin@example.com',
            'password': 'Password123!'
        })
        self.admin_token = login_resp.data['access']
        
        login_resp_viewer = self.client.post('/api/auth/login/', {
            'identifier': 'viewer1@example.com',
            'password': 'Password123!'
        })
        self.viewer_token = login_resp_viewer.data['access']

    def test_overview_endpoint(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.admin_token}')
        response = self.client.get('/api/admin/dashboard/overview/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total_viewers'], 3) # viewer1, viewer2, admintemp created in test -> Wait, default role is Viewer
        # Actually admintemp will default to Viewer. So 3 viewers.
        self.assertEqual(response.data['total_producers'], 1)
        self.assertEqual(response.data['total_movies'], 2)
        self.assertEqual(response.data['total_views'], 25)
        self.assertEqual(response.data['financials']['total_revenue'], 3000)
        self.assertEqual(response.data['financials']['producer_revenue'], 2100)
        self.assertEqual(response.data['financials']['ikigembe_commission'], 900)

    def test_viewers_list_endpoint(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.admin_token}')
        response = self.client.get('/api/admin/dashboard/viewers/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Verify viewer 1
        viewer1_data = next(v for v in response.data if v['email'] == 'viewer1@example.com')
        self.assertEqual(viewer1_data['movies_watched'], 1) # Only completed payments count
        self.assertEqual(viewer1_data['payments_made'], 1000)

    def test_user_suspend_endpoint(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.admin_token}')
        self.assertTrue(self.viewer1.is_active)
        
        response = self.client.post(f'/api/admin/dashboard/users/{self.viewer1.id}/suspend/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.viewer1.refresh_from_db()
        self.assertFalse(self.viewer1.is_active)

    def test_user_delete_endpoint(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.admin_token}')
        response = self.client.delete(f'/api/admin/dashboard/users/{self.viewer1.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(User.objects.filter(id=self.viewer1.id).exists())

    def test_producers_list_endpoint(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.admin_token}')
        response = self.client.get('/api/admin/dashboard/producers/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        producer_data = response.data[0]
        self.assertEqual(producer_data['email'], 'producer@example.com')
        self.assertEqual(producer_data['movies_uploaded'], 2)
        self.assertEqual(producer_data['total_earnings'], 2100)
        self.assertEqual(producer_data['balance'], 1100) # 2100 - 1000 withdrawn

    def test_producer_approve_endpoint(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.admin_token}')
        self.producer.is_active = False
        self.producer.save()
        
        response = self.client.post(f'/api/admin/dashboard/producers/{self.producer.id}/approve/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.producer.refresh_from_db()
        self.assertTrue(self.producer.is_active)

    def test_permission_denied_for_viewers(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.viewer_token}')
        response = self.client.get('/api/admin/dashboard/overview/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
