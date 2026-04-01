import re
import requests
from datetime import datetime, timezone
from django.conf import settings

SANDBOX_URL = 'https://api.sandbox.pawapay.cloud'
LIVE_URL = 'https://api.pawapay.cloud'

# Rwanda MTN prefixes: 078, 079 → international: 25078, 25079
# Rwanda Airtel prefixes: 072, 073 → international: 25072, 25073
_CORRESPONDENT_MAP = {
    '78': 'MTN_MOMO_RWA',
    '79': 'MTN_MOMO_RWA',
    '72': 'AIRTEL_OAPI_RWA',
    '73': 'AIRTEL_OAPI_RWA',
}


def _clean_description(text: str) -> str:
    """Remove non-alphanumeric characters (except spaces) and truncate to 22 chars."""
    return re.sub(r'[^a-zA-Z0-9 ]', '', text)[:22]


def _post(endpoint: str, payload: dict) -> dict:
    """POST to a PawaPay API endpoint and return the JSON response."""
    base_url = getattr(settings, 'PAWAPAY_BASE_URL', SANDBOX_URL)
    response = requests.post(
        f'{base_url}/{endpoint}',
        json=payload,
        headers={
            'Authorization': f'Bearer {settings.PAWAPAY_API_KEY}',
            'Content-Type': 'application/json',
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def normalize_phone(phone: str) -> str:
    """Convert any Rwanda phone format to international format (e.g. 250781234567)."""
    phone = phone.strip().replace(' ', '').replace('-', '')
    if phone.startswith('+'):
        return phone[1:]
    if phone.startswith('0'):
        return '250' + phone[1:]
    return phone


def detect_correspondent(phone: str) -> str | None:
    """
    Detect PawaPay correspondent code from a Rwanda phone number.
    Returns None if the prefix is unrecognized.
    """
    normalized = normalize_phone(phone)
    local = normalized[3:] if normalized.startswith('250') else normalized
    return _CORRESPONDENT_MAP.get(local[:2])


def initiate_deposit(deposit_id: str, amount: int, phone_number: str, description: str = 'Ikigembe') -> dict:
    """
    Initiate a mobile money deposit via PawaPay.
    Raises ValueError for unrecognized phone prefix.
    Raises requests.HTTPError on non-2xx responses.
    """
    correspondent = detect_correspondent(phone_number)
    if not correspondent:
        raise ValueError(f"Unrecognized Rwanda phone prefix for number: {phone_number}")

    return _post('deposits', {
        'depositId': str(deposit_id),
        'amount': str(amount),
        'currency': 'RWF',
        'correspondent': correspondent,
        'payer': {
            'type': 'MSISDN',
            'address': {'value': normalize_phone(phone_number)},
        },
        'customerTimestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'statementDescription': _clean_description(description),
    })


def initiate_payout(payout_id: str, amount: int, phone_number: str, description: str = 'Ikigembe Payout') -> dict:
    """
    Initiate a mobile money payout to a producer via PawaPay.
    Raises ValueError for unrecognized phone prefix.
    Raises requests.HTTPError on non-2xx responses.
    """
    correspondent = detect_correspondent(phone_number)
    if not correspondent:
        raise ValueError(f"Unrecognized Rwanda phone prefix for number: {phone_number}")

    return _post('payouts', {
        'payoutId': str(payout_id),
        'amount': str(amount),
        'currency': 'RWF',
        'correspondent': correspondent,
        'recipient': {
            'type': 'MSISDN',
            'address': {'value': normalize_phone(phone_number)},
        },
        'customerTimestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'statementDescription': _clean_description(description),
    })
