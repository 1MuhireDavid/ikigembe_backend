from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

User = get_user_model()



class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(
        read_only=True,
        help_text='User's full name (concatenation of first and last name).'
    )

    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'full_name', 'avatar_url', 'is_staff', 'date_joined']
        read_only_fields = fields
        extra_kwargs = {
            'id': {'help_text': 'Unique user ID.'},
            'email': {'help_text': 'User\'s email address.'},
            'first_name': {'help_text': 'User\'s first name.'},
            'last_name': {'help_text': 'User\'s last name.'},
            'avatar_url': {'help_text': 'URL to user\'s profile picture (from Google or Gravatar).'},
            'is_staff': {'help_text': 'Whether user has staff privileges.'},
            'date_joined': {'help_text': 'Date and time when the account was created.'},
        }


# ─────────────────────────────────────────────
# Registration
# ─────────────────────────────────────────────

class RegisterSerializer(serializers.ModelSerializer):
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

    class Meta:
        model = User
        fields = ['email', 'password', 'password_confirm', 'first_name', 'last_name']
        extra_kwargs = {
            'email': {
                'help_text': 'A valid email address. Must be unique.',
                'error_messages': {
                    'required': 'Email is required.',
                    'invalid': 'Enter a valid email address.',
                }
            },
            'first_name': {
                'help_text': 'User's first name (optional).',
                'required': False,
            },
            'last_name': {
                'help_text': 'User's last name (optional).',
                'required': False,
            },
        }

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({'password': 'Passwords do not match.'})
        return attrs

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


# ─────────────────────────────────────────────
# Login
# ─────────────────────────────────────────────

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(
        help_text='Email address of the user account.'
    )
    password = serializers.CharField(
        write_only=True,
        help_text='Password for the user account.',
        style={'input_type': 'password'}
    )

    def validate(self, attrs):
        from django.contrib.auth import authenticate
        email = attrs.get('email', '').strip().lower()
        password = attrs.get('password')

        user = authenticate(request=self.context.get('request'), email=email, password=password)

        if not user:
            raise serializers.ValidationError('Invalid email or password.')
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
