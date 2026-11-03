import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from tests.test_tenant_auth import FakeSession, ForbiddenSession, make_client
from webhook_platform.models import Tenant
from webhook_platform.security import generate_api_key

BODY = {"type": "order.paid", "payload": {"order_id": 1}}


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {generate_api_key()}"}


def authenticated_client() -> TestClient:
    tenant = Tenant(id=uuid.uuid4(), name="acme", created_at=datetime.now(UTC))
    return make_client(FakeSession(tenant=tenant))


def test_events_require_api_key() -> None:
    client = make_client(ForbiddenSession())

    response = client.post("/events", json=BODY, headers={"Idempotency-Key": "k1"})

    assert response.status_code == 401


def test_events_require_idempotency_key() -> None:
    client = authenticated_client()

    assert client.post("/events", json=BODY, headers=auth()).status_code == 422


def test_events_reject_invalid_type() -> None:
    client = authenticated_client()

    response = client.post(
        "/events",
        json={"type": "Order Paid", "payload": {}},
        headers={**auth(), "Idempotency-Key": "k1"},
    )

    assert response.status_code == 422
