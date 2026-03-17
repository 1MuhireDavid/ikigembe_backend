from django.contrib.auth.models import BaseUserManager


class UserManager(BaseUserManager):
    """Manager for the custom User model (email or phone number as identifier)."""

    def create_user(self, email=None, password=None, **extra_fields):
        phone_number = extra_fields.get('phone_number')

        if not email and not phone_number:
            raise ValueError('Either an email address or a phone number is required.')

        if email:
<<<<<<< HEAD
            # normalize_email() lowercases only the domain; .lower() covers the local part too
            email = self.normalize_email(email).lower()
=======
            email = self.normalize_email(email)
>>>>>>> ef07f8817c67b9293428454c431a22c7e54d8ff8

        if phone_number:
            extra_fields['phone_number'] = phone_number.strip()

        extra_fields.setdefault('is_active', True)
        user = self.model(email=email, **extra_fields)

        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()

        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if not extra_fields.get('is_staff'):
            raise ValueError('Superuser must have is_staff=True.')
        if not extra_fields.get('is_superuser'):
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, password, **extra_fields)
