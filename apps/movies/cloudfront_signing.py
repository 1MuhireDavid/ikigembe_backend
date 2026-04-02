import logging
from datetime import datetime, timezone, timedelta

from django.conf import settings

logger = logging.getLogger(__name__)


def sign_hls_url(plain_url: str, expiry_seconds: int = 3600) -> str:
    """
    Return a CloudFront signed URL valid for `expiry_seconds`.

    Requires CLOUDFRONT_KEY_PAIR_ID and CLOUDFRONT_PRIVATE_KEY in settings.
    Falls back to the plain URL if signing is not configured (e.g. local dev).
    """
    key_pair_id = getattr(settings, 'CLOUDFRONT_KEY_PAIR_ID', None)
    private_key_pem = getattr(settings, 'CLOUDFRONT_PRIVATE_KEY', None)

    if not key_pair_id or not private_key_pem:
        logger.debug('CloudFront signing not configured — returning plain URL')
        return plain_url

    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from botocore.signers import CloudFrontSigner

        pem_bytes = (
            private_key_pem.encode()
            if isinstance(private_key_pem, str)
            else private_key_pem
        )

        def rsa_signer(message):
            private_key = serialization.load_pem_private_key(pem_bytes, password=None)
            return private_key.sign(message, padding.PKCS1v15(), hashes.SHA1())

        expire_at = datetime.now(tz=timezone.utc) + timedelta(seconds=expiry_seconds)
        return CloudFrontSigner(key_pair_id, rsa_signer).generate_presigned_url(
            plain_url, date_less_than=expire_at
        )
    except Exception:
        logger.exception('Failed to sign CloudFront URL — returning plain URL')
        return plain_url
