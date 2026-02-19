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

from .serializers import (
    GoogleAuthSerializer,
    LoginSerializer,
    RegisterSerializer,
    UserSerializer,
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
    Create a new user account with email and password.
    Returns JWT access + refresh tokens on success.
    """
    permission_classes = [AllowAny]

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
    Authenticate with email and password.
    Returns JWT access + refresh tokens on success.
    """
    permission_classes = [AllowAny]

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

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)


# ─────────────────────────────────────────────
# Logout (blacklist refresh token)
# ─────────────────────────────────────────────

class LogoutView(APIView):
    """
    Invalidate the provided refresh token.
    The access token will expire naturally per its lifetime setting.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response({'error': 'Refresh token is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            RefreshToken(refresh_token).blacklist()
        except TokenError:
            pass  # Already invalid — that's fine

        return Response(status=status.HTTP_205_RESET_CONTENT)
