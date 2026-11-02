import pytest
from pydantic import ValidationError

from webhook_platform.config import Settings

URL = "postgresql+asyncpg://user:secret-pass@localhost:5432/db"
TOKEN = "admin-secret-token"


def test_settings_are_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)

    settings = Settings(_env_file=None)

    assert settings.database_url.get_secret_value() == URL
    assert settings.admin_token.get_secret_value() == TOKEN


def test_missing_database_url_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_missing_admin_token_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_secrets_are_not_exposed_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)

    text = repr(Settings(_env_file=None))

    assert "secret-pass" not in text
    assert TOKEN not in text
