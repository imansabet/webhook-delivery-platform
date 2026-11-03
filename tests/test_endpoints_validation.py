import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from tests.test_tenant_auth import FakeSession, ForbiddenSession, make_client
from webhook_platform.models import Tenant
from webhook_platform.security import generate_api_key


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {generate_api_key()}"}


def make_authenticated_client() -> TestClient:
    tenant = Tenant(id=uuid.uuid4(), name="acme", created_at=datetime.now(UTC))
    return make_client(FakeSession(tenant=tenant))


def test_endpoints_require_api_key() -> None:
    client = make_client(ForbiddenSession())

    assert client.get("/endpoints").status_code == 401
    assert client.post("/endpoints", json={"url": "https://example.com/h"}).status_code == 401
    assert client.delete(f"/endpoints/{uuid.uuid4()}").status_code == 401


def test_create_endpoint_rejects_private_destination() -> None:
    client = make_authenticated_client()

    response = client.post(
        "/endpoints", json={"url": "https://169.254.169.254/latest"}, headers=auth()
    )

    assert response.status_code == 422


def test_list_rejects_out_of_range_limit() -> None:
    client = make_authenticated_client()

    assert client.get("/endpoints?limit=0", headers=auth()).status_code == 422
    assert client.get("/endpoints?limit=101", headers=auth()).status_code == 422


def test_get_endpoint_with_invalid_id_is_422() -> None:
    client = make_authenticated_client()

    assert client.get("/endpoints/not-a-uuid", headers=auth()).status_code == 422
