import pytest

from webhook_platform.urls import validate_destination_url


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/webhook",
        "https://hooks.example.co.uk:8443/a?b=1",
        "https://8.8.8.8/hook",
        "https://xn--mnchen-3ya.de/hook",
    ],
)
def test_valid_destinations_are_accepted(url: str) -> None:
    assert validate_destination_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/hook",
        "ftp://example.com/hook",
        "",
        "https:///path",
        "https://localhost/hook",
        "https://app.localhost/hook",
        "https://127.0.0.1/hook",
        "https://10.0.0.5/hook",
        "https://192.168.1.1/hook",
        "https://172.16.0.1/hook",
        "https://169.254.169.254/latest/meta-data/",
        "https://[::1]/hook",
        "https://[::ffff:127.0.0.1]/hook",
        "https://db/hook",
        "https://service.internal/hook",
        "https://printer.local/hook",
        "https://0x7f.0.0.1/hook",
        "https://2130706433/hook",
        "https://user:pass@example.com/hook",
        "https://example.com:99999/hook",
        "https://example.com./hook",
        "https://example.com/" + "a" * 2100,
    ],
)
def test_dangerous_or_malformed_destinations_are_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        validate_destination_url(url)
