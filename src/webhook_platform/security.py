import base64
import hashlib
import hmac
import secrets
import binascii

API_KEY_PREFIX = "whk_"
WEBHOOK_SECRET_PREFIX = "whsec_"


def generate_api_key() -> str:
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def display_prefix(key: str) -> str:
    return key[:8]


def generate_webhook_secret() -> str:
    return WEBHOOK_SECRET_PREFIX + base64.b64encode(secrets.token_bytes(32)).decode()


def sign_webhook(secret: str, message_id: str, timestamp: int, body: bytes) -> str:
    key = base64.b64decode(secret.removeprefix(WEBHOOK_SECRET_PREFIX))
    signed_content = f"{message_id}.{timestamp}.".encode() + body
    digest = hmac.new(key, signed_content, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode()


def verify_webhook(
    secret: str,
    message_id: str,
    timestamp_header: str,
    signature_header: str,
    body: bytes,
    *,
    now: float,
    tolerance_seconds: int = 300,
) -> bool:
    try:
        timestamp = int(timestamp_header)
    except ValueError:
        return False
    if abs(now - timestamp) > tolerance_seconds:
        return False

    expected = sign_webhook(secret, message_id, timestamp, body).encode()
    return any(
        hmac.compare_digest(candidate.encode(), expected)
        for candidate in signature_header.split(" ")
    )


def validate_webhook_secret(secret: str) -> bool:
    if not secret.startswith(WEBHOOK_SECRET_PREFIX):
        return False

    encoded_key = secret.removeprefix(WEBHOOK_SECRET_PREFIX)
    try:
        key = base64.b64decode(encoded_key, validate=True)
    except (ValueError,binascii.Error):
        return False

    return len(key) == 32
