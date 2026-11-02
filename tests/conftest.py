from collections.abc import Iterator

import pytest

from webhook_platform.main import app


@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()
