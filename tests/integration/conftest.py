from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer

from webhook_platform.config import Settings, get_settings
from webhook_platform.db import get_session
from webhook_platform.main import app

ROOT = Path(__file__).resolve().parents[2]
ADMIN_TOKEN = "integration-admin-token-0123456789"


@dataclass(frozen=True)
class TenantAccount:
    id: str
    api_key: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer("postgres:17", driver="asyncpg") as postgres:
        url = postgres.get_connection_url()

        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "migrations"))
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("DATABASE_URL", url)
            patch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
            get_settings.cache_clear()
            command.upgrade(config, "head")
            get_settings.cache_clear()

        yield url


@pytest_asyncio.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(text("truncate table tenants cascade"))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def client(engine: AsyncEngine, database_url: str) -> AsyncIterator[httpx.AsyncClient]:
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    settings = Settings(_env_file=None, database_url=database_url, admin_token=ADMIN_TOKEN)
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: settings

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def scalar(engine: AsyncEngine) -> Callable[..., Awaitable[Any]]:
    async def run(sql: str, **params: Any) -> Any:
        async with engine.connect() as connection:
            return (await connection.execute(text(sql), params)).scalar_one()

    return run


@pytest_asyncio.fixture
async def execute(engine: AsyncEngine) -> Callable[..., Awaitable[None]]:
    async def run(sql: str, **params: Any) -> None:
        async with engine.begin() as connection:
            await connection.execute(text(sql), params)

    return run


@pytest.fixture
def make_tenant(client: httpx.AsyncClient) -> Callable[[str], Awaitable[TenantAccount]]:
    async def make(name: str) -> TenantAccount:
        response = await client.post(
            "/tenants",
            json={"name": name},
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        return TenantAccount(id=body["tenant"]["id"], api_key=body["api_key"])

    return make


@pytest.fixture
def add_endpoint(client: httpx.AsyncClient) -> Callable[..., Awaitable[dict[str, Any]]]:
    async def add(
        account: TenantAccount,
        url: str = "https://example.com/hook",
        event_types: list[str] | None = None,
    ) -> dict[str, Any]:
        response = await client.post(
            "/endpoints",
            json={"url": url, "event_types": event_types or ["*"]},
            headers=account.headers,
        )
        assert response.status_code == 201, response.text
        return response.json()  # type: ignore[no-any-return]

    return add


@pytest.fixture
def send_event(client: httpx.AsyncClient) -> Callable[..., Awaitable[httpx.Response]]:
    async def send(
        account: TenantAccount,
        idempotency_key: str,
        event_type: str = "order.paid",
        payload: dict[str, Any] | None = None,
    ) -> httpx.Response:
        return await client.post(
            "/events",
            json={"type": event_type, "payload": payload or {"n": 1}},
            headers={**account.headers, "Idempotency-Key": idempotency_key},
        )

    return send


@pytest.fixture
def sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def column(engine: AsyncEngine) -> Callable[..., Awaitable[list[Any]]]:
    async def run(sql: str, **params: Any) -> list[Any]:
        async with engine.connect() as connection:
            return [row[0] for row in await connection.execute(text(sql), params)]

    return run
