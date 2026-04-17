import uuid
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework import serializers as drf_serializers
from drf_spectacular.utils import extend_schema, inline_serializer, OpenApiResponse, OpenApiExample
from .serializers import (
    GoogleAuthSerializer,
    LoginSerializer,
    NotificationPreferencesSerializer,
    ProfileUpdateSerializer,
    RegisterSerializer,
    UserSerializer,
    RefreshSerializer
)
from .emails import send_welcome_email, send_password_reset_email
from .models import FailedLoginAttempt

User = get_user_model()


# Role → front-end panel mapping
_ROLE_REDIRECT = {
    'Admin': '/admin-panel',
    'Producer': '/producer-panel',
    'Viewer': '/movie-gallery',
}


def _token_response(user):
    """
    Build a standard token + user payload for the given user.

    Generates a new session key on every call (i.e. every login/register),
    saves it to the user record, and embeds it in both the access and refresh
    tokens.  The custom SingleSessionJWTAuthentication class reads this claim
    on every request and rejects tokens whose key no longer matches the DB —
    effectively kicking any previously logged-in device off the moment a new
    login occurs.
    """
    session_key = str(uuid.uuid4())
    user.active_session_key = session_key
    user.save(update_fields=['active_session_key'])

    refresh = RefreshToken.for_user(user)
    # Embed role in the JWT payload to prevent front-end spoofing.
    refresh['session_key'] = session_key
    refresh.access_token['role'] = user.role
    refresh.access_token['email'] = user.email or ''
    refresh.access_token['session_key'] = session_key
    return {
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'user': UserSerializer(user).data,
        'redirect_to': _ROLE_REDIRECT.get(user.role, '/movie-gallery'),
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
            201: inline_serializer(
                name='RegisterResponse',
                fields={
                    'access': drf_serializers.CharField(help_text='JWT access token (expires in 30 minutes)'),
                    'refresh': drf_serializers.CharField(help_text='JWT refresh token (expires in 7 days)'),
                    'user': UserSerializer(),
                    'redirect_to': drf_serializers.CharField(help_text='Frontend route to redirect to after login'),
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
        send_welcome_email(user)
        return Response(_token_response(user), status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────
# Login
# ─────────────────────────────────────────────

_LOCKOUT_MAX_ATTEMPTS = 5
_LOCKOUT_WINDOW_MINUTES = 15


def _get_client_ip(request):
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '0.0.0.0')


def _is_locked_out(ip, identifier):
    window = timezone.now() - timedelta(minutes=_LOCKOUT_WINDOW_MINUTES)
    return FailedLoginAttempt.objects.filter(
        ip_address=ip,
        identifier__iexact=identifier,
        created_at__gte=window,
    ).count() >= _LOCKOUT_MAX_ATTEMPTS


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
        ip = _get_client_ip(request)
        identifier = request.data.get('identifier', '').strip()

        if identifier and _is_locked_out(ip, identifier):
            return Response(
                {'error': f'Too many failed login attempts. Please try again in {_LOCKOUT_WINDOW_MINUTES} minutes.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        serializer = LoginSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            if identifier:
                FailedLoginAttempt.objects.create(ip_address=ip, identifier=identifier)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user = serializer.validated_data['user']
        FailedLoginAttempt.objects.filter(ip_address=ip, identifier__iexact=identifier).delete()
        data = _token_response(user)
        return Response(data, status=status.HTTP_200_OK)


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
                send_welcome_email(user)

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
            access = refresh.access_token

            user_id = refresh.payload.get('user_id')

            user = User.objects.filter(pk=user_id).only(
                'id', 'role', 'email', 'is_active', 'active_session_key'
            ).first()
            if user:
                if not user.is_active:
                    return Response(
                        {'error': 'This account has been deactivated.'},
                        status=status.HTTP_401_UNAUTHORIZED,
                    )

                # Reject the refresh if the session key in the token no longer
                # matches the one stored in the database.  This prevents a
                # device that was kicked out (because the user logged in
                # elsewhere) from silently obtaining a new access token.
                token_session_key = refresh.payload.get('session_key')
                if token_session_key and user.active_session_key != token_session_key:
                    return Response(
                        {'error': 'Your session has been terminated. Please log in again.'},
                        status=status.HTTP_401_UNAUTHORIZED,
                    )

                access['role'] = user.role
                access['email'] = user.email or ''
                if token_session_key:
                    access['session_key'] = token_session_key

            data = {'access': str(access)}

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
    """Return or update the authenticated user's profile."""
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

    @extend_schema(
        request=ProfileUpdateSerializer,
        responses={
            200: UserSerializer(),
            400: OpenApiResponse(description='Validation error'),
            401: OpenApiResponse(description='Authentication credentials were not provided'),
        },
        tags=['User'],
        summary='Update current user profile',
        description=(
            'Update first name, last name, email, phone number, or avatar URL. '
            'At least one of email or phone number must remain set.'
        ),
    )
    def patch(self, request):
        serializer = ProfileUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserSerializer(request.user).data)


# ─────────────────────────────────────────────
# Password Reset
# ─────────────────────────────────────────────

class ForgotPasswordView(APIView):
    """Request a password-reset email using email or phone."""
    permission_classes = [AllowAny]

    @extend_schema(
        tags=['Authentication'],
        summary='Request password reset',
        description=(
            'Send a password-reset link to the email address associated with the account. '
            'Accepts either an email address or phone number as `identifier`. '
            'Always returns 200 to avoid account enumeration.'
        ),
        request=inline_serializer(
            name='ForgotPasswordRequest',
            fields={'identifier': drf_serializers.CharField(help_text='Email or phone number')},
        ),
        responses={200: inline_serializer(
            name='ForgotPasswordResponse',
            fields={'message': drf_serializers.CharField()},
        )},
    )
    def post(self, request):
        from .models import PasswordResetToken
        identifier = (request.data.get('identifier') or '').strip()
        user = (
            User.objects.filter(email__iexact=identifier).first()
            or User.objects.filter(phone_number=identifier).first()
        )
        # Send the reset email only when the account has an email address.
        # Phone-only accounts and unknown identifiers all receive the same
        # response to prevent account enumeration.
        if user and user.email:
            token_obj = PasswordResetToken.make(user)
            send_password_reset_email(user, token_obj.token)

        return Response({
            'message': (
                'If an account with that identifier exists and has a registered email address, '
                'a password reset link has been sent. '
                'For phone-only accounts, please contact Ikigembe support — '
                'an admin can generate a temporary password.'
            )
        })


class ResetPasswordView(APIView):
    """Consume a reset token and set a new password."""
    permission_classes = [AllowAny]

    @extend_schema(
        tags=['Authentication'],
        summary='Reset password with token',
        description='Provide the token from the reset email and a new password.',
        request=inline_serializer(
            name='ResetPasswordRequest',
            fields={
                'token': drf_serializers.CharField(),
                'new_password': drf_serializers.CharField(style={'input_type': 'password'}),
                'confirm_password': drf_serializers.CharField(style={'input_type': 'password'}),
            },
        ),
        responses={
            200: inline_serializer(
                name='ResetPasswordResponse',
                fields={'message': drf_serializers.CharField()},
            ),
            400: OpenApiResponse(description='Invalid/expired token or password mismatch'),
        },
    )
    def post(self, request):
        from .models import PasswordResetToken
        from django.contrib.auth.password_validation import validate_password
        from django.db import transaction as db_transaction

        token_str = (request.data.get('token') or '').strip()
        new_password = request.data.get('new_password', '')
        confirm_password = request.data.get('confirm_password', '')

        if not token_str:
            return Response({'error': 'Token is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if new_password != confirm_password:
            return Response({'error': 'Passwords do not match.'}, status=status.HTTP_400_BAD_REQUEST)

        # Validate password before acquiring the lock — avoids holding the row
        # lock while Django runs password validators.
        try:
            # Fetch without lock first just to get the user for validation.
            token_obj = PasswordResetToken.objects.select_related('user').get(token=token_str)
        except PasswordResetToken.DoesNotExist:
            return Response({'error': 'Invalid or expired reset token.'}, status=status.HTTP_400_BAD_REQUEST)

        if not token_obj.is_valid():
            return Response({'error': 'This reset link has expired. Please request a new one.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            validate_password(new_password, token_obj.user)
        except Exception as e:
            return Response({'error': list(e.messages) if hasattr(e, 'messages') else str(e)},
                            status=status.HTTP_400_BAD_REQUEST)

        # Atomic: re-fetch with row lock, re-validate, then commit all changes
        # together to close the TOCTOU window.
        with db_transaction.atomic():
            try:
                token_obj = PasswordResetToken.objects.select_for_update().select_related('user').get(
                    token=token_str, used=False
                )
            except PasswordResetToken.DoesNotExist:
                return Response({'error': 'Invalid or expired reset token.'}, status=status.HTTP_400_BAD_REQUEST)

            if not token_obj.is_valid():
                return Response({'error': 'This reset link has expired. Please request a new one.'}, status=status.HTTP_400_BAD_REQUEST)

            token_obj.used = True
            token_obj.save(update_fields=['used'])

            # Rotate session key so all existing JWTs are immediately invalidated
            # (Fix 3: reset must revoke outstanding tokens)
            user = token_obj.user
            user.set_password(new_password)
            user.active_session_key = str(uuid.uuid4())
            user.save(update_fields=['password', 'active_session_key'])

        return Response({'message': 'Password reset successfully. You can now log in.'})


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


# ─────────────────────────────────────────────
# Change Password
# ─────────────────────────────────────────────

class ChangePasswordView(APIView):
    """Allow an authenticated user to change their password."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Authentication"],
        summary="Change password",
        description="Change the authenticated user's password. Requires the current password for verification.",
    )
    def post(self, request):
        current = request.data.get('current_password')
        new = request.data.get('new_password')
        confirm = request.data.get('confirm_password')

        if not current or not new or not confirm:
            return Response(
                {'error': 'current_password, new_password, and confirm_password are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not request.user.check_password(current):
            return Response({'error': 'Current password is incorrect.'}, status=status.HTTP_400_BAD_REQUEST)
        if new != confirm:
            return Response({'error': 'Passwords do not match.'}, status=status.HTTP_400_BAD_REQUEST)
        if len(new) < 8:
            return Response({'error': 'Password must be at least 8 characters.'}, status=status.HTTP_400_BAD_REQUEST)

        request.user.set_password(new)
        request.user.active_session_key = str(uuid.uuid4())
        request.user.save(update_fields=['password', 'active_session_key'])
        return Response({'message': 'Password updated successfully. Please log in again.'})


# ─────────────────────────────────────────────
# Notification Preferences
# ─────────────────────────────────────────────

class NotificationsView(APIView):
    """
    GET  — retrieve the authenticated user's notification preferences.
    PATCH — update one or more notification preferences.
    All preferences default to True at registration (opted in).
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: NotificationPreferencesSerializer()},
        tags=['User'],
        summary='Get notification preferences',
    )
    def get(self, request):
        serializer = NotificationPreferencesSerializer(request.user)
        return Response(serializer.data)

    @extend_schema(
        request=NotificationPreferencesSerializer,
        responses={200: NotificationPreferencesSerializer()},
        tags=['User'],
        summary='Update notification preferences',
        description='Send only the fields you want to change. Unspecified fields are left untouched.',
    )
    def patch(self, request):
        serializer = NotificationPreferencesSerializer(
            request.user, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
