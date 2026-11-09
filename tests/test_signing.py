import base64

from webhook_platform.security import (
    WEBHOOK_SECRET_PREFIX,
    generate_webhook_secret,
    sign_webhook,
    verify_webhook,
)

SECRET = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"
MESSAGE_ID = "msg_p5jXN8AQM9LWM0D4loKWxJek"
TIMESTAMP = 1614265330
BODY = b'{"test": 2432232314}'
SPEC_SIGNATURE = "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE="


def test_signature_matches_the_published_standard_webhooks_vector() -> None:
    assert sign_webhook(SECRET, MESSAGE_ID, TIMESTAMP, BODY) == SPEC_SIGNATURE


def test_signature_binds_body_id_and_timestamp() -> None:
    assert sign_webhook(SECRET, MESSAGE_ID, TIMESTAMP, b'{"test": 2432232315}') != SPEC_SIGNATURE
    assert sign_webhook(SECRET, "msg_other", TIMESTAMP, BODY) != SPEC_SIGNATURE
    assert sign_webhook(SECRET, MESSAGE_ID, TIMESTAMP + 1, BODY) != SPEC_SIGNATURE


def test_generated_secret_is_a_prefixed_base64_key_of_32_bytes() -> None:
    secret = generate_webhook_secret()

    assert secret.startswith(WEBHOOK_SECRET_PREFIX)
    assert len(base64.b64decode(secret.removeprefix(WEBHOOK_SECRET_PREFIX))) == 32
    assert secret != generate_webhook_secret()


def test_verify_accepts_valid_signature() -> None:
    assert verify_webhook(
        SECRET, MESSAGE_ID, str(TIMESTAMP), SPEC_SIGNATURE, BODY, now=TIMESTAMP + 10
    )


def test_verify_rejects_tampered_body_or_bad_signature() -> None:
    now = TIMESTAMP + 10
    assert not verify_webhook(SECRET, MESSAGE_ID, str(TIMESTAMP), SPEC_SIGNATURE, b"{}", now=now)
    assert not verify_webhook(SECRET, MESSAGE_ID, str(TIMESTAMP), "v1,AAAA", BODY, now=now)
    assert not verify_webhook(SECRET, MESSAGE_ID, "not-a-number", SPEC_SIGNATURE, BODY, now=now)


def test_verify_rejects_replay_outside_tolerance() -> None:
    too_late = TIMESTAMP + 301
    too_early = TIMESTAMP - 301

    assert not verify_webhook(
        SECRET, MESSAGE_ID, str(TIMESTAMP), SPEC_SIGNATURE, BODY, now=too_late
    )
    assert not verify_webhook(
        SECRET, MESSAGE_ID, str(TIMESTAMP), SPEC_SIGNATURE, BODY, now=too_early
    )


def test_verify_accepts_one_valid_signature_among_several() -> None:
    header = f"v1,AAAA v2,BBBB {SPEC_SIGNATURE}"

    assert verify_webhook(SECRET, MESSAGE_ID, str(TIMESTAMP), header, BODY, now=TIMESTAMP)
