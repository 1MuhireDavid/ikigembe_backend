from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


class RegisterTests(APITestCase):
    url = '/api/auth/register/'

    def test_register_with_email_only(self):
        data = {
            'email': 'emailonly@example.com',
            'password': 'StrongPass1!',
            'password_confirm': 'StrongPass1!',
        }
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertEqual(response.data['user']['email'], 'emailonly@example.com')
        self.assertIsNone(response.data['user']['phone_number'])

    def test_register_with_phone_only(self):
        data = {
            'phone_number': '+250781234567',
            'password': 'StrongPass1!',
            'password_confirm': 'StrongPass1!',
        }
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('access', response.data)
        self.assertEqual(response.data['user']['phone_number'], '+250781234567')
        self.assertIsNone(response.data['user']['email'])

    def test_register_with_email_and_phone(self):
        data = {
            'email': 'both@example.com',
            'phone_number': '+250789999999',
            'password': 'StrongPass1!',
            'password_confirm': 'StrongPass1!',
        }
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['user']['email'], 'both@example.com')
        self.assertEqual(response.data['user']['phone_number'], '+250789999999')

    def test_register_with_neither_fails(self):
        data = {
            'password': 'StrongPass1!',
            'password_confirm': 'StrongPass1!',
        }
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_password_mismatch_fails(self):
        data = {
            'email': 'mismatch@example.com',
            'password': 'StrongPass1!',
            'password_confirm': 'Different1!',
        }
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_duplicate_email_fails(self):
        data = {
            'email': 'dup@example.com',
            'password': 'StrongPass1!',
            'password_confirm': 'StrongPass1!',
        }
        self.client.post(self.url, data)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_duplicate_phone_fails(self):
        data = {
            'phone_number': '+250700000001',
            'password': 'StrongPass1!',
            'password_confirm': 'StrongPass1!',
        }
        self.client.post(self.url, data)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class LoginTests(APITestCase):
    url = '/api/auth/login/'

    def setUp(self):
        reg_url = '/api/auth/register/'
        self.client.post(reg_url, {
            'email': 'login@example.com',
            'password': 'StrongPass1!',
            'password_confirm': 'StrongPass1!',
        })
        self.client.post(reg_url, {
            'phone_number': '+250711111111',
            'password': 'StrongPass1!',
            'password_confirm': 'StrongPass1!',
        })

    def test_login_with_email(self):
        response = self.client.post(self.url, {
            'identifier': 'login@example.com',
            'password': 'StrongPass1!',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)

    def test_login_with_phone(self):
        response = self.client.post(self.url, {
            'identifier': '+250711111111',
            'password': 'StrongPass1!',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)

    def test_login_wrong_password_fails(self):
        response = self.client.post(self.url, {
            'identifier': 'login@example.com',
            'password': 'WrongPass1!',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_unknown_identifier_fails(self):
        response = self.client.post(self.url, {
            'identifier': 'nobody@example.com',
            'password': 'StrongPass1!',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
