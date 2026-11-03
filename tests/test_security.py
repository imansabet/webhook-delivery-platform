from webhook_platform.security import (
    API_KEY_PREFIX,
    WEBHOOK_SECRET_PREFIX,
    display_prefix,
    generate_api_key,
    generate_webhook_secret,
    hash_api_key,
)


def test_generated_key_has_prefix_and_enough_length() -> None:
    key = generate_api_key()

    assert key.startswith(API_KEY_PREFIX)
    assert len(key) >= 40


def test_generated_keys_are_unique() -> None:
    keys = {generate_api_key() for _ in range(1000)}

    assert len(keys) == 1000


def test_hash_matches_known_sha256_vector() -> None:
    assert hash_api_key("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_hash_is_deterministic_and_hides_the_key() -> None:
    key = generate_api_key()

    assert hash_api_key(key) == hash_api_key(key)
    assert key not in hash_api_key(key)
    assert len(hash_api_key(key)) == 64


def test_display_prefix_is_short_and_not_the_whole_key() -> None:
    key = generate_api_key()
    assert display_prefix(key) == key[:8]
    assert len(display_prefix(key)) == 8


def test_webhook_secret_has_prefix_and_is_unique() -> None:
    secrets_ = {generate_webhook_secret() for _ in range(1000)}

    assert len(secrets_) == 1000
    assert all(s.startswith(WEBHOOK_SECRET_PREFIX) for s in secrets_)
