import hashlib
import secrets

API_KEY_PREFIX = "whk_"
WEBHOOK_SECRET_PREFIX = "whsec_"


def generate_api_key() -> str:
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def display_prefix(key: str) -> str:
    return key[:8]


def generate_webhook_secret() -> str:
    return WEBHOOK_SECRET_PREFIX + secrets.token_urlsafe(32)
