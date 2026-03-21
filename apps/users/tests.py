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


# ──────────────────────────────────────────────────────────────────────────────
# Role Registration Tests
# ──────────────────────────────────────────────────────────────────────────────

class RoleRegistrationTests(APITestCase):
    """Tests for role field behaviour during registration."""
    url = '/api/auth/register/'

    def test_default_role_is_viewer(self):
        """Registering without specifying a role should default to Viewer."""
        response = self.client.post(self.url, {
            'email': 'viewer@example.com',
            'password': 'StrongPass1!',
            'password_confirm': 'StrongPass1!',
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['user']['role'], 'Viewer')

    def test_register_with_producer_role(self):
        """Explicitly registering as Producer should persist the role."""
        response = self.client.post(self.url, {
            'email': 'producer@example.com',
            'password': 'StrongPass1!',
            'password_confirm': 'StrongPass1!',
            'role': 'Producer',
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['user']['role'], 'Producer')

    def test_register_with_admin_role(self):
        """Explicitly registering as Admin should persist the role."""
        response = self.client.post(self.url, {
            'email': 'admin@example.com',
            'password': 'StrongPass1!',
            'password_confirm': 'StrongPass1!',
            'role': 'Admin',
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['user']['role'], 'Admin')

    def test_invalid_role_is_rejected(self):
        """An unrecognised role value should return 400."""
        response = self.client.post(self.url, {
            'email': 'badrole@example.com',
            'password': 'StrongPass1!',
            'password_confirm': 'StrongPass1!',
            'role': 'SuperAdmin',
        })
        self.assertEqual(response.status_code, 400)


# ──────────────────────────────────────────────────────────────────────────────
# Role Login Response Tests
# ──────────────────────────────────────────────────────────────────────────────

import base64
import json as _json

class RoleLoginTests(APITestCase):
    """Tests that login responses include role and correct redirect_to."""
    reg_url = '/api/auth/register/'
    login_url = '/api/auth/login/'

    def _register_and_login(self, email, role):
        self.client.post(self.reg_url, {
            'email': email,
            'password': 'StrongPass1!',
            'password_confirm': 'StrongPass1!',
            'role': role,
        })
        return self.client.post(self.login_url, {
            'identifier': email,
            'password': 'StrongPass1!',
        })

    def _decode_jwt_payload(self, token):
        """Base64-decode the JWT payload segment (no verification needed)."""
        payload_b64 = token.split('.')[1]
        # Pad if needed
        payload_b64 += '=' * (-len(payload_b64) % 4)
        return _json.loads(base64.urlsafe_b64decode(payload_b64))

    def test_viewer_login_returns_correct_redirect(self):
        response = self._register_and_login('viewer2@example.com', 'Viewer')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['user']['role'], 'Viewer')
        self.assertEqual(response.data['redirect_to'], '/movie-gallery')

    def test_producer_login_returns_correct_redirect(self):
        response = self._register_and_login('producer2@example.com', 'Producer')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['user']['role'], 'Producer')
        self.assertEqual(response.data['redirect_to'], '/producer-panel')

    def test_admin_login_returns_correct_redirect(self):
        response = self._register_and_login('admin2@example.com', 'Admin')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['user']['role'], 'Admin')
        self.assertEqual(response.data['redirect_to'], '/admin-panel')

    def test_jwt_payload_contains_role_claim(self):
        """The JWT access token must carry a role claim to prevent front-end spoofing."""
        response = self._register_and_login('jwttest@example.com', 'Producer')
        self.assertEqual(response.status_code, 200)
        payload = self._decode_jwt_payload(response.data['access'])
        self.assertEqual(payload.get('role'), 'Producer')

    def test_jwt_payload_contains_email_claim(self):
        response = self._register_and_login('jwtmail@example.com', 'Viewer')
        self.assertEqual(response.status_code, 200)
        payload = self._decode_jwt_payload(response.data['access'])
        self.assertEqual(payload.get('email'), 'jwtmail@example.com')


# ──────────────────────────────────────────────────────────────────────────────
# Role-Protected Route Tests
# ──────────────────────────────────────────────────────────────────────────────

from django.contrib.auth import get_user_model

User = get_user_model()


class RoleProtectedRoutesTests(APITestCase):
    """Tests that movie Admin routes enforce IsAdminRole (403 for non-Admins)."""
    reg_url = '/api/auth/register/'
    login_url = '/api/auth/login/'
    create_url = '/api/movies/create/'

    def _get_token(self, email, role):
        """Register a user with a given role and return their access token."""
        self.client.post(self.reg_url, {
            'email': email,
            'password': 'StrongPass1!',
            'password_confirm': 'StrongPass1!',
            'role': role,
        })
        resp = self.client.post(self.login_url, {
            'identifier': email,
            'password': 'StrongPass1!',
        })
        return resp.data['access']

    def test_admin_can_reach_movie_create(self):
        """Admin role should pass the permission check (400 not 403 — missing body is ok)."""
        token = self._get_token('admin_route@example.com', 'Admin')
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        response = self.client.post(self.create_url, {})
        # 400 means the request reached the view; 403 would mean permission denied
        self.assertNotEqual(response.status_code, 403)

    def test_viewer_cannot_reach_movie_create(self):
        """Viewer role must receive 403 Forbidden on Admin-only routes."""
        token = self._get_token('viewer_route@example.com', 'Viewer')
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        response = self.client.post(self.create_url, {})
        self.assertEqual(response.status_code, 403)

    def test_producer_cannot_reach_movie_create(self):
        """Producer role must receive 403 Forbidden on Admin-only routes."""
        token = self._get_token('producer_route@example.com', 'Producer')
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        response = self.client.post(self.create_url, {})
        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_cannot_reach_movie_create(self):
        """Unauthenticated requests must be rejected (401)."""
        self.client.credentials()  # clear any auth
        response = self.client.post(self.create_url, {})
        self.assertEqual(response.status_code, 401)
