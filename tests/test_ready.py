from collections.abc import AsyncIterator

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from webhook_platform.db import get_session
from webhook_platform.main import app


class FakeSession:
    def __init__(self, fail: bool) -> None:
        self.fail = fail

    async def execute(self, statement: object) -> None:
        if self.fail:
            raise OperationalError("select 1", {}, Exception("db down"))


def override_session(fail: bool):
    async def _get() -> AsyncIterator[FakeSession]:
        yield FakeSession(fail)

    return _get


def test_ready_ok_when_database_answers() -> None:
    app.dependency_overrides[get_session] = override_session(fail=False)
    try:
        response = TestClient(app).get("/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_ready_returns_503_when_database_fails() -> None:
    app.dependency_overrides[get_session] = override_session(fail=True)
    try:
        response = TestClient(app).get("/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert "db down" not in response.text
