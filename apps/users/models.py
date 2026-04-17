import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.utils import timezone
from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom User model.
    Supports email/phone + password and Google OAuth2 authentication.
    At least one of email or phone_number must be provided.
    """

    class Role(models.TextChoices):
        ADMIN = 'Admin', 'Admin'
        PRODUCER = 'Producer', 'Producer'
        VIEWER = 'Viewer', 'Viewer'
    email = models.EmailField(unique=True, null=True, blank=True, db_index=True)
    phone_number = models.CharField(max_length=20, unique=True, null=True, blank=True, db_index=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)


    address = models.CharField(max_length=255, blank=True, null=True, default='')
    copyright_code = models.CharField(max_length=100, blank=True, null=True, default='')

    google_id = models.CharField(max_length=255, unique=True, null=True, blank=True, db_index=True)
    avatar_url = models.URLField(max_length=500, blank=True, null=True)

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.VIEWER,
        db_index=True,
    )

    # Single-session enforcement: stores the key of the only valid active session.
    # A new login rotates this key, immediately invalidating tokens from other devices.
    active_session_key = models.CharField(max_length=36, blank=True, null=True)

    # Notification preferences — all opted in by default per acceptance criteria.
    notify_new_trailers = models.BooleanField(default=True)
    notify_new_movies = models.BooleanField(default=True)
    notify_promotions = models.BooleanField(default=True)

    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = 'user'
        verbose_name_plural = 'users'
        ordering = ['-date_joined']

    def __str__(self):
        return self.email or self.phone_number or f'User #{self.pk}'

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()


class AdminAuditLog(models.Model):
    ACTION_CHOICES = [
        ('suspend_user',        'Suspend/Activate User'),
        ('delete_user',         'Delete User'),
        ('approve_producer',    'Approve Producer'),
        ('suspend_producer',    'Suspend Producer'),
        ('create_producer',     'Create Producer'),
        ('approve_withdrawal',   'Approve Withdrawal'),
        ('complete_withdrawal',  'Complete Withdrawal'),
        ('reject_withdrawal',    'Reject Withdrawal'),
        ('reset_user_password',  'Reset User Password'),
        ('view_viewer_pii',      'View Viewer PII (dispute/support)'),
        ('resolve_payment',      'Manually Resolve Payment'),
    ]

    admin               = models.ForeignKey(
                            settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                            null=True, related_name='audit_logs')
    action              = models.CharField(max_length=30, choices=ACTION_CHOICES)
    target_user         = models.ForeignKey(
                            settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                            null=True, blank=True, related_name='audit_targets')
    target_withdrawal   = models.ForeignKey(
                            'payments.WithdrawalRequest', on_delete=models.SET_NULL,
                            null=True, blank=True)
    detail              = models.JSONField(default=dict)
    ip_address          = models.GenericIPAddressField(null=True, blank=True)
    timestamp           = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        admin_email = self.admin.email if self.admin else 'unknown'
        return f'{admin_email} → {self.action} at {self.timestamp}'


class PasswordResetToken(models.Model):
    """Single-use token for password recovery. Valid for 1 hour."""
    EXPIRY_HOURS = 1

    user       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                   related_name='password_reset_tokens')
    token      = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    used       = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    @classmethod
    def make(cls, user):
        """Invalidate previous tokens and create a fresh one."""
        cls.objects.filter(user=user, used=False).update(used=True)
        return cls.objects.create(user=user, token=secrets.token_urlsafe(48))

    def is_valid(self):
        if self.used:
            return False
        return timezone.now() < self.created_at + timedelta(hours=self.EXPIRY_HOURS)

    def __str__(self):
        return f'reset token for {self.user} (used={self.used})'


class FailedLoginAttempt(models.Model):
    """One row per failed login attempt. Used for brute-force detection."""
    ip_address = models.GenericIPAddressField(db_index=True)
    identifier = models.CharField(max_length=255, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['ip_address', 'identifier', 'created_at']),
        ]

    def __str__(self):
        return f'failed login from {self.ip_address} for "{self.identifier}"'
