import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from webhook_platform.config import Settings, get_settings
from webhook_platform.db import get_session
from webhook_platform.main import app
from webhook_platform.models import Tenant
from webhook_platform.security import generate_api_key

ADMIN_TOKEN = "test-admin-token-0123456789"
SETTINGS = Settings(
    _env_file=None,
    database_url="postgresql+asyncpg://u:p@localhost/db",
    admin_token=ADMIN_TOKEN,
)


class FakeResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value


class FakeSession:
    def __init__(self, tenant: object | None = None) -> None:
        self.tenant = tenant

    async def execute(self, statement: object) -> FakeResult:
        return FakeResult(self.tenant)


class ForbiddenSession:
    async def execute(self, statement: object) -> FakeResult:
        raise AssertionError("database must not be touched")


def make_client(session: object) -> TestClient:
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


def test_create_tenant_rejects_missing_and_wrong_admin_token() -> None:
    client = make_client(ForbiddenSession())
    body = {"name": "acme"}

    missing = client.post("/tenants", json=body)
    wrong = client.post("/tenants", json=body, headers={"Authorization": "Bearer nope"})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert wrong.headers["www-authenticate"] == "Bearer"


def test_me_requires_credentials() -> None:
    client = make_client(ForbiddenSession())

    assert client.get("/tenants/me").status_code == 401


def test_me_rejects_malformed_key_without_touching_database() -> None:
    client = make_client(ForbiddenSession())

    response = client.get("/tenants/me", headers={"Authorization": "Bearer garbage"})

    assert response.status_code == 401


def test_me_rejects_unknown_key() -> None:
    client = make_client(FakeSession(tenant=None))

    response = client.get("/tenants/me", headers={"Authorization": f"Bearer {generate_api_key()}"})

    assert response.status_code == 401


def test_me_returns_tenant_for_valid_key() -> None:
    tenant = Tenant(id=uuid.uuid4(), name="acme", created_at=datetime.now(UTC))
    client = make_client(FakeSession(tenant=tenant))

    response = client.get("/tenants/me", headers={"Authorization": f"Bearer {generate_api_key()}"})

    assert response.status_code == 200
    assert response.json()["name"] == "acme"
    assert set(response.json()) == {"id", "name", "created_at"}
