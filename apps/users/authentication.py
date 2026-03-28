from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from drf_spectacular.extensions import OpenApiAuthenticationExtension


class SingleSessionJWTAuthentication(JWTAuthentication):
    """
    Extends the default JWT authentication to enforce single-session logins.

    Each login/register stores a UUID ``session_key`` on the User record and
    embeds it as a claim in both the access and refresh tokens.  When this
    authenticator processes an access token it compares the embedded key
    against the value currently stored in the database.  A mismatch means
    the user has logged in from another device, so the old token is rejected
    immediately — no need to wait for it to expire.
    """

    def get_user(self, validated_token):
        user = super().get_user(validated_token)

        token_session_key = validated_token.get('session_key')

        # Only enforce the check when the token actually carries a session key.
        # Tokens issued before this feature was deployed won't have the claim,
        # and we don't want to lock everyone out on the first deployment.
        if token_session_key and user.active_session_key != token_session_key:
            raise AuthenticationFailed(
                'Your session has been terminated because you logged in from '
                'another device. Please log in again.',
                code='session_terminated',
            )

        return user


class SingleSessionJWTAuthenticationExtension(OpenApiAuthenticationExtension):
    """Tell drf-spectacular how to document SingleSessionJWTAuthentication."""
    target_class = 'apps.users.authentication.SingleSessionJWTAuthentication'
    name = 'bearerAuth'

    def get_security_requirement(self, auto_schema):
        return {self.name: []}

    def get_security_definition(self, auto_schema):
        return {
            'type': 'http',
            'scheme': 'bearer',
            'bearerFormat': 'JWT',
            'description': 'JWT access token. Tokens are invalidated when the user logs in from another device.',
        }
