from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

User = get_user_model()



class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(
        read_only=True,
        help_text='User\'s full name (concatenation of first and last name).'
    )

    class Meta:
        model = User
        fields = [
            'id', 'email', 'phone_number',
            'first_name', 'last_name', 'full_name',
            'avatar_url', 'is_staff', 'role', 'is_active', 'date_joined',
            'notify_new_trailers', 'notify_new_movies', 'notify_promotions',
        ]
        read_only_fields = fields
        extra_kwargs = {
            'id': {'help_text': 'Unique user ID.'},
            'email': {'help_text': 'User\'s email address.'},
            'first_name': {'help_text': 'User\'s first name.'},
            'last_name': {'help_text': 'User\'s last name.'},
            'avatar_url': {'help_text': 'URL to user\'s profile picture (from Google or Gravatar).'},
            'is_staff': {'help_text': 'Whether user has staff privileges.'},
            'role': {'help_text': 'User role: Admin, Producer, or Viewer.'},
            'is_active': {'help_text': 'Whether the user account is active or deactivated.'},
            'date_joined': {'help_text': 'Date and time when the account was created.'},
            'notify_new_trailers': {'help_text': 'Receive notifications for new trailers.'},
            'notify_new_movies': {'help_text': 'Receive notifications for new movie releases.'},
            'notify_promotions': {'help_text': 'Receive notifications for promotions and deals.'},
        }


class NotificationPreferencesSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['notify_new_trailers', 'notify_new_movies', 'notify_promotions']



class RegisterSerializer(serializers.ModelSerializer):
    """
    Serializer for user registration.
    Either email or phone_number must be provided (or both).
    """

    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password],
        help_text='Password must be at least 8 characters and contain uppercase, lowercase, numbers, and special characters.',
        style={'input_type': 'password'}
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=True,
        help_text='Must match the password field above.',
        style={'input_type': 'password'}
    )


    email = serializers.EmailField(
        required=False,
        allow_blank=True,
        default=None,
        help_text='Email address. Required if phone_number is not provided.'
    )
    phone_number = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=20,
        default=None,
        help_text='Phone number (e.g. +250781234567). Required if email is not provided.'
    )
    first_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=150,
        default='',
        help_text="User's first name (optional)."
    )
    last_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=150,
        default='',
        help_text="User's last name (optional). "
    )

    class Meta:
        model = User
        fields = ['email', 'phone_number', 'password', 'password_confirm', 'first_name', 'last_name']

    def validate_email(self, value):
        if not value:
            return None
        return value.lower().strip()

    def validate_phone_number(self, value):
        if value is None:
            return value
        return value.strip()

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({'password': 'Passwords do not match.'})

        email = attrs.get('email')
        phone_number = attrs.get('phone_number')

        if not email and not phone_number:
            raise serializers.ValidationError(
                'At least one of email or phone number is required.'
            )

        if email and User.objects.filter(email=email).exists():
            raise serializers.ValidationError({'email': 'A user with this email already exists.'})

        if phone_number and User.objects.filter(phone_number=phone_number).exists():
            raise serializers.ValidationError({'phone_number': 'A user with this phone number already exists.'})

        return attrs

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        email = validated_data.pop('email', None) or None
        phone_number = validated_data.pop('phone_number', None) or None

        user = User.objects.create_user(
            email=email,
            password=password,
            phone_number=phone_number,
            # role intentionally omitted — all new registrations start as Viewer
            **validated_data,
        )
        return user



class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField(
        help_text='Email address or phone number registered on this account.'
    )
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        identifier = attrs.get('identifier', '').strip()
        password = attrs.get('password')

        
        user = (
            User.objects.filter(email__iexact=identifier).first()
            or User.objects.filter(phone_number=identifier).first()
        )

        if not user or not user.check_password(password):
            raise serializers.ValidationError('Invalid credentials.')

        if not user.is_active:
            raise serializers.ValidationError('This account has been deactivated.')

        attrs['user'] = user
        return attrs


class GoogleAuthSerializer(serializers.Serializer):
    id_token = serializers.CharField(
        help_text='Google ID token obtained from the frontend Google Sign-In flow.'
    )

class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField(
        help_text="The refresh token obtained during login or registration"
    )

class ProfileUpdateSerializer(serializers.ModelSerializer):
    """Allow a user to update their own profile fields."""
    email = serializers.EmailField(required=False, allow_null=True, allow_blank=True)
    phone_number = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=20)
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    avatar_url = serializers.URLField(required=False, allow_null=True, allow_blank=True)

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone_number', 'avatar_url']

    def validate_email(self, value):
        if not value:
            return None
        value = value.lower().strip()
        qs = User.objects.filter(email=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

    def validate_phone_number(self, value):
        if not value:
            return None
        value = value.strip()
        qs = User.objects.filter(phone_number=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('A user with this phone number already exists.')
        return value

    def validate(self, attrs):
        # Ensure at least one contact method remains after update
        email = attrs.get('email', self.instance.email if self.instance else None)
        phone = attrs.get('phone_number', self.instance.phone_number if self.instance else None)
        if not email and not phone:
            raise serializers.ValidationError('At least one of email or phone number is required.')
        return attrs


class AdminCreateProducerSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password],
        help_text='Password must be at least 8 characters and contain uppercase, lowercase, numbers, and special characters.',
        style={'input_type': 'password'}
    )
    email = serializers.EmailField(
        required=False,
        allow_blank=True,
        default=None,
        help_text='Email address. Required if phone_number is not provided.'
    )
    phone_number = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=20,
        default=None,
        help_text='Phone number (e.g. +250781234567). Required if email is not provided.'
    )
    first_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=150,
        default='',
        help_text="User's first name."
    )
    last_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=150,
        default='',
        help_text="User's last name."
    )

    class Meta:
        model = User
        fields = ['email', 'phone_number', 'password', 'first_name', 'last_name']

    def validate_email(self, value):
        if value == '':
            return None
        return value.lower().strip()

    def validate_phone_number(self, value):
        if value is None:
            return value
        return value.strip()

    def validate(self, attrs):
        email = attrs.get('email')
        phone_number = attrs.get('phone_number')

        if not email and not phone_number:
            raise serializers.ValidationError(
                'At least one of email or phone number is required.'
            )

        if email and User.objects.filter(email=email).exists():
            raise serializers.ValidationError({'email': 'A user with this email already exists.'})

        if phone_number and User.objects.filter(phone_number=phone_number).exists():
            raise serializers.ValidationError({'phone_number': 'A user with this phone number already exists.'})

        return attrs

    def create(self, validated_data):
        password = validated_data.pop('password')
        email = validated_data.pop('email', None) or None
        phone_number = validated_data.pop('phone_number', None) or None

        user = User.objects.create_user(
            email=email,
            password=password,
            phone_number=phone_number,
            role=User.Role.PRODUCER,
            **validated_data
        )
        return user
