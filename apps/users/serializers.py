from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

User = get_user_model()


# ─────────────────────────────────────────────
# User representation (safe, read-only)
# ─────────────────────────────────────────────

class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'email', 'phone_number',
            'first_name', 'last_name', 'full_name',
            'avatar_url', 'is_staff', 'date_joined',
        ]
        read_only_fields = fields


# ─────────────────────────────────────────────
# Registration
# ─────────────────────────────────────────────

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True, required=True)

    # Both are optional individually — validated together below
    email = serializers.EmailField(required=False, allow_blank=True, default=None)
    phone_number = serializers.CharField(required=False, allow_blank=True, max_length=20, default=None)

    class Meta:
        model = User
        fields = ['email', 'phone_number', 'password', 'password_confirm', 'first_name', 'last_name']

    def validate_email(self, value):
        if value == '':
            return None
        return value.lower().strip()

    def validate_phone_number(self, value):
        if value == '':
            return None
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

        # Check uniqueness manually so we get friendly errors
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
            **validated_data,
        )
        return user


# ─────────────────────────────────────────────
# Login
# ─────────────────────────────────────────────

class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField(
        help_text='Email address or phone number registered on this account.'
    )
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        identifier = attrs.get('identifier', '').strip()
        password = attrs.get('password')

        # Try email first, then phone number
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


# ─────────────────────────────────────────────
# Google OAuth2
# ─────────────────────────────────────────────

class GoogleAuthSerializer(serializers.Serializer):
    id_token = serializers.CharField(
        help_text='Google ID token obtained from the frontend Google Sign-In flow.'
    )

