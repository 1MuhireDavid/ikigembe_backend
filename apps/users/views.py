from django.conf import settings
from django.contrib.auth import get_user_model
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from drf_spectacular.utils import extend_schema, OpenApiResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample
from .serializers import (
    GoogleAuthSerializer,
    LoginSerializer,
    RegisterSerializer,
    UserSerializer,
    RefreshSerializer
)

User = get_user_model()


def _token_response(user):
    """Build a standard token + user payload for a given user."""
    refresh = RefreshToken.for_user(user)
    return {
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'user': UserSerializer(user).data,
    }


# ─────────────────────────────────────────────
# Register
# ─────────────────────────────────────────────

class RegisterView(APIView):
    """
    Create a new user account using either an email address or a phone number (or both).
    Returns JWT access + refresh tokens on success.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        request=RegisterSerializer,
        responses={
            201: OpenApiResponse(
                description='User successfully registered',
                response={
                    'type': 'object',
                    'properties': {
                        'access': {'type': 'string', 'description': 'JWT access token (expires in 30 minutes)'},
                        'refresh': {'type': 'string', 'description': 'JWT refresh token (expires in 7 days)'},
                        'user': {
                            'type': 'object',
                            'description': 'User profile information',
                            'properties': {
                                'id': {'type': 'integer'},
                                'email': {'type': 'string', 'nullable': True, 'description': 'Email address (null if registered with phone only)'},
                                'phone_number': {'type': 'string', 'nullable': True, 'description': 'Phone number (null if registered with email only)'},
                                'first_name': {'type': 'string'},
                                'last_name': {'type': 'string'},
                                'full_name': {'type': 'string'},
                                'avatar_url': {'type': 'string', 'nullable': True},
                                'is_staff': {'type': 'boolean'},
                                'date_joined': {'type': 'string', 'format': 'date-time'},
                            }
                        }
                    }
                },
            ),
            400: OpenApiResponse(description='Invalid input (validation errors)'),
        },
        tags=['Authentication'],
        summary='Register a new user account',
        description=(
            'Create a new user account. You must supply **at least one** of `email` or `phone_number` '
            '(you may provide both). Passwords must be strong: 8+ characters, mixed case, numbers, and symbols.\n\n'
            '**Registration options:**\n'
            '- Email only: provide `email`, omit or leave `phone_number` blank.\n'
            '- Phone only: provide `phone_number`, omit or leave `email` blank.\n'
            '- Both: provide both `email` and `phone_number`.'
        ),
        examples=[
            OpenApiExample(
                'Register with Email Only',
                summary='Register using an email address',
                value={
                    'email': 'user@example.com',
                    'password': 'SecurePass123!',
                    'password_confirm': 'SecurePass123!',
                    'first_name': 'John',
                    'last_name': 'Doe',
                },
                request_only=True,
            ),
            OpenApiExample(
                'Register with Phone Number Only',
                summary='Register using a phone number',
                value={
                    'phone_number': '+250781234567',
                    'password': 'SecurePass123!',
                    'password_confirm': 'SecurePass123!',
                    'first_name': 'Jane',
                    'last_name': 'Doe',
                },
                request_only=True,
            ),
            OpenApiExample(
                'Register with Both Email and Phone',
                summary='Register providing both email and phone number',
                value={
                    'email': 'user@example.com',
                    'phone_number': '+250781234567',
                    'password': 'SecurePass123!',
                    'password_confirm': 'SecurePass123!',
                    'first_name': 'John',
                    'last_name': 'Doe',
                },
                request_only=True,
            ),
            OpenApiExample(
                'Register Response',
                summary='Successful registration response',
                value={
                    'access': 'eyJ0eXAiOiJKV1QiLCJhbGc...',
                    'refresh': 'eyJ0eXAiOiJKV1QiLCJhbGc...',
                    'user': {
                        'id': 1,
                        'email': 'user@example.com',
                        'phone_number': None,
                        'first_name': 'John',
                        'last_name': 'Doe',
                        'full_name': 'John Doe',
                        'avatar_url': None,
                        'is_staff': False,
                        'date_joined': '2024-03-14T10:30:00Z',
                    }
                },
                response_only=True,
            ),
        ],
    )
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(_token_response(user), status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────
# Login
# ─────────────────────────────────────────────

class LoginView(APIView):
    """
    Authenticate with email or phone number + password.
    Returns JWT access + refresh tokens on success.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        request=LoginSerializer,
        responses={
            200: OpenApiResponse(
                description='User successfully authenticated',
                response={
                    'type': 'object',
                    'properties': {
                        'access': {'type': 'string', 'description': 'JWT access token (expires in 30 minutes)'},
                        'refresh': {'type': 'string', 'description': 'JWT refresh token (expires in 7 days)'},
                        'user': {
                            'type': 'object',
                            'description': 'User profile information',
                        }
                    }
                },
            ),
            400: OpenApiResponse(description='Invalid credentials'),
        },
        tags=['Authentication'],
        summary='Login with email or phone number',
        description=(
            'Authenticate a user using their **email address or phone number** together with their password.\n\n'
            'Pass the email or phone number as the `identifier` field.'
        ),
        examples=[
            OpenApiExample(
                'Login with Email',
                summary='Use email address as identifier',
                value={
                    'identifier': 'user@example.com',
                    'password': 'SecurePass123!',
                },
                request_only=True,
            ),
            OpenApiExample(
                'Login with Phone Number',
                summary='Use phone number as identifier',
                value={
                    'identifier': '+250781234567',
                    'password': 'SecurePass123!',
                },
                request_only=True,
            ),
        ],
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        return Response(_token_response(user), status=status.HTTP_200_OK)


# ─────────────────────────────────────────────
# Google Sign-In / Sign-Up
# ─────────────────────────────────────────────

class GoogleAuthView(APIView):
    """
    Authenticate (or register) a user via Google Sign-In.

    Expects a POST body: { "id_token": "<Google ID token from frontend>" }

    Flow:
      1. Verify the Google ID token server-side.
      2. If a user with matching google_id exists → log them in.
      3. If a user with matching email exists → link google_id and log in.
      4. Otherwise → create a new account and log in.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        request=GoogleAuthSerializer,
        responses={
            200: OpenApiResponse(description='User authenticated or created via Google'),
            400: OpenApiResponse(description='Invalid or missing Google ID token'),
            503: OpenApiResponse(description='Google Sign-In not configured on server'),
        },
        tags=['Authentication'],
        summary='Authenticate with Google Sign-In',
        description='Sign in or register using a Google ID token. If email exists, links Google ID to existing account.',
    )
    def post(self, request):
        serializer = GoogleAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        raw_token = serializer.validated_data['id_token']
        client_id = getattr(settings, 'GOOGLE_OAUTH2_CLIENT_ID', '')

        if not client_id:
            return Response(
                {'error': 'Google Sign-In is not configured on this server.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Verify token with Google
        try:
            id_info = google_id_token.verify_oauth2_token(
                raw_token,
                google_requests.Request(),
                client_id,
            )
        except ValueError as exc:
            return Response(
                {'error': f'Invalid Google token: {exc}'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        google_id = id_info.get('sub')
        email = id_info.get('email', '').lower()
        first_name = id_info.get('given_name', '')
        last_name = id_info.get('family_name', '')
        avatar_url = id_info.get('picture', '')

        if not email:
            return Response(
                {'error': 'Google account has no associated email.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Try to find existing user
        user = User.objects.filter(google_id=google_id).first()

        if not user:
            user = User.objects.filter(email=email).first()
            if user:
                # Link google_id to existing email account
                user.google_id = google_id
                user.avatar_url = avatar_url or user.avatar_url
                user.save(update_fields=['google_id', 'avatar_url'])
            else:
                # Brand new user via Google
                user = User.objects.create_user(
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    google_id=google_id,
                    avatar_url=avatar_url,
                )

        return Response(_token_response(user), status=status.HTTP_200_OK)


# ─────────────────────────────────────────────
# Token Refresh
# ─────────────────────────────────────────────

class TokenRefreshView(APIView):
    """
    Exchange a valid refresh token for a new access token.
    With ROTATE_REFRESH_TOKENS=True a new refresh token is also returned.
    """
    permission_classes = [AllowAny]

    @extend_schema(
    request=RefreshSerializer,
    responses={
        200: OpenApiResponse(description="New access token generated"),
        400: OpenApiResponse(description="Refresh token is required"),
        401: OpenApiResponse(description="Invalid or expired refresh token"),
    },
    tags=["Authentication"],
    summary="Refresh access token",
    )
    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response({'error': 'Refresh token is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            refresh = RefreshToken(refresh_token)
            data = {'access': str(refresh.access_token)}
            # Rotate the refresh token if configured
            if settings.SIMPLE_JWT.get('ROTATE_REFRESH_TOKENS'):
                refresh.set_jti()
                refresh.set_exp()
                data['refresh'] = str(refresh)
            return Response(data)
        except TokenError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_401_UNAUTHORIZED)


# ─────────────────────────────────────────────
# Me (current user profile)
# ─────────────────────────────────────────────

class MeView(APIView):
    """Return the authenticated user's profile."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={
            200: UserSerializer(),
            401: OpenApiResponse(description='Authentication credentials were not provided'),
        },
        tags=['User'],
        summary='Get current user profile',
        description='Retrieve the profile information of the authenticated user.',
    )
    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)


class LogoutView(APIView):
    """
    Invalidate the provided refresh token.
    The access token will expire naturally per its lifetime setting.
    """
    permission_classes = [IsAuthenticated]


    @extend_schema(
        request=RefreshSerializer,
        responses={
            205: OpenApiResponse(description="Successfully logged out"),
            400: OpenApiResponse(description="Refresh token is required"),
            401: OpenApiResponse(description="Authentication credentials were not provided"),
        },
        tags=["Authentication"],
        summary="Logout user",
    )
    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response({'error': 'Refresh token is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            RefreshToken(refresh_token).blacklist()
        except TokenError:
            pass  # Already invalid — that's fine

        return Response(status=status.HTTP_205_RESET_CONTENT)
