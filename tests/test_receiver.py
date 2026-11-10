import time

import pytest
from fastapi.testclient import TestClient

from webhook_platform.devtools import receiver
from webhook_platform.security import generate_webhook_secret, sign_webhook

BODY = b'{"hello":"world"}'
client = TestClient(receiver.app)


@pytest.fixture(autouse=True)
def reset_receiver_state() -> None:
    receiver.secrets_registry.clear()
    receiver.received.clear()
    receiver.seen_ids.clear()


def signed_headers(secret: str, message_id: str, timestamp: int | None = None) -> dict[str, str]:
    moment = int(time.time()) if timestamp is None else timestamp
    return {
        "webhook-id": message_id,
        "webhook-timestamp": str(moment),
        "webhook-signature": sign_webhook(secret, message_id, moment, BODY),
    }


def register(secret: str) -> None:
    assert client.put("/dev/secret", json={"secret": secret}).status_code == 200


def test_valid_signature_is_accepted_and_repeated_ids_are_flagged() -> None:
    secret = generate_webhook_secret()
    register(secret)

    first = client.post("/hook", content=BODY, headers=signed_headers(secret, "msg_1"))
    second = client.post("/hook", content=BODY, headers=signed_headers(secret, "msg_1"))

    log = client.get("/dev/received").json()
    assert first.status_code == 200
    assert second.status_code == 200
    assert [(item["verified"], item["duplicate"]) for item in log] == [
        (True, False),
        (True, True),
    ]


def test_invalid_requests_are_rejected_and_never_marked_as_seen() -> None:
    secret = generate_webhook_secret()
    register(secret)
    old = int(time.time()) - 3600

    responses = [
        client.post("/hook", content=b"{}", headers=signed_headers(secret, "msg_1")),
        client.post("/hook", content=BODY),
        client.post("/hook", content=BODY, headers=signed_headers(secret, "msg_2", old)),
        client.post(
            "/hook", content=BODY, headers=signed_headers(generate_webhook_secret(), "msg_3")
        ),
    ]

    assert [response.status_code for response in responses] == [401, 401, 401, 401]
    assert not any(item["verified"] for item in client.get("/dev/received").json())
    assert receiver.seen_ids == set()


def test_nothing_is_verified_until_a_secret_is_registered() -> None:
    secret = generate_webhook_secret()

    response = client.post("/hook", content=BODY, headers=signed_headers(secret, "msg_1"))

    assert response.status_code == 401


def test_status_and_slow_endpoints_validate_their_arguments() -> None:
    assert client.post("/status/503", content=BODY).status_code == 503
    assert client.post("/status/199", content=BODY).status_code == 422
    assert client.post("/status/600", content=BODY).status_code == 422
    assert client.post("/slow/0", content=BODY).status_code == 200
    assert client.post("/slow/31", content=BODY).status_code == 422


def test_invalid_secret_is_rejected_and_log_can_be_cleared() -> None:
    assert client.put("/dev/secret", json={"secret": "whsec_***"}).status_code == 422

    client.post("/status/200", content=BODY)
    assert len(client.get("/dev/received").json()) == 1
    assert client.delete("/dev/received").status_code == 204
    assert client.get("/dev/received").json() == []
