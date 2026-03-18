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
    email = models.EmailField(unique=True, null=True, blank=True, db_index=True)
    phone_number = models.CharField(max_length=20, unique=True, null=True, blank=True, db_index=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)

    # Google OAuth2
    google_id = models.CharField(max_length=255, unique=True, null=True, blank=True, db_index=True)
    avatar_url = models.URLField(max_length=500, blank=True, null=True)

    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []  # email is implied

    class Meta:
        verbose_name = 'user'
        verbose_name_plural = 'users'
        ordering = ['-date_joined']

    def __str__(self):
        return self.email or self.phone_number or f'User #{self.pk}'

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()
