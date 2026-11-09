import socket

import httpx
import pytest

from webhook_platform.sender import send_webhook

SECRET = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"
BODY = b'{"test": 2432232314}'
SPEC_SIGNATURE = "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE="
MESSAGE_ID = "msg_p5jXN8AQM9LWM0D4loKWxJek"


def resolver_for(mapping: dict[str, list[str]]):
    async def resolve(host: str, port: int) -> list[str]:
        if host not in mapping:
            raise socket.gaierror("unknown host")
        return mapping[host]

    return resolve


class Recorder:
    def __init__(self, response: httpx.Response | Exception) -> None:
        self.requests: list[httpx.Request] = []
        self.response = response

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


async def send(url: str, recorder: Recorder, mapping: dict[str, list[str]], **options):
    async with httpx.AsyncClient(transport=httpx.MockTransport(recorder)) as client:
        return await send_webhook(
            client,
            url=url,
            secret=SECRET,
            message_id=MESSAGE_ID,
            body=BODY,
            resolver=resolver_for(mapping),
            clock=lambda: 1614265330,
            **options,
        )


async def test_request_is_signed_and_pinned_to_the_validated_address() -> None:
    recorder = Recorder(httpx.Response(200))

    result = await send(
        "https://hooks.example.com/in/coming?x=1",
        recorder,
        {"hooks.example.com": ["93.184.216.34"]},
    )

    request = recorder.requests[0]
    assert result.ok
    assert result.status_code == 200
    assert request.url.host == "93.184.216.34"
    assert request.url.path == "/in/coming"
    assert request.url.query == b"x=1"
    assert request.headers["host"] == "hooks.example.com"
    assert request.extensions["sni_hostname"] == "hooks.example.com"
    assert request.headers["webhook-id"] == MESSAGE_ID
    assert request.headers["webhook-timestamp"] == "1614265330"
    assert request.headers["webhook-signature"] == SPEC_SIGNATURE
    assert request.content == BODY


@pytest.mark.parametrize("status_code", [301, 400, 404, 500, 503])
async def test_non_2xx_is_a_failure_and_redirects_are_not_followed(status_code: int) -> None:
    recorder = Recorder(httpx.Response(status_code, headers={"Location": "http://10.0.0.1/"}))

    result = await send(
        "https://hooks.example.com/h", recorder, {"hooks.example.com": ["93.184.216.34"]}
    )

    assert not result.ok
    assert result.status_code == status_code
    assert len(recorder.requests) == 1


@pytest.mark.parametrize(
    ("url", "addresses"),
    [
        ("https://hooks.example.com/h", ["10.0.0.5"]),
        ("https://hooks.example.com/h", ["127.0.0.1"]),
        ("https://hooks.example.com/h", ["169.254.169.254"]),
        ("https://hooks.example.com/h", ["::1"]),
        ("https://hooks.example.com/h", ["::ffff:127.0.0.1"]),
        ("https://hooks.example.com/h", ["93.184.216.34", "127.0.0.1"]),
        ("https://127.0.0.1/h", ["127.0.0.1"]),
        ("https://169.254.169.254/latest/meta-data/", ["169.254.169.254"]),
        ("http://hooks.example.com/h", ["93.184.216.34"]),
        ("https://db/h", ["172.18.0.2"]),
    ],
)
async def test_destinations_that_are_not_public_are_never_contacted(
    url: str, addresses: list[str]
) -> None:
    recorder = Recorder(httpx.Response(200))

    result = await send(url, recorder, {"hooks.example.com": addresses, "db": addresses})

    assert not result.ok
    assert result.error == "destination not allowed"
    assert recorder.requests == []


async def test_dns_failure_is_reported_without_sending() -> None:
    recorder = Recorder(httpx.Response(200))

    result = await send("https://missing.example.com/h", recorder, {})

    assert result.error == "dns resolution failed"
    assert recorder.requests == []


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (httpx.ConnectTimeout("connect to 10.0.0.5 timed out"), "timeout"),
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ConnectError("connection to 10.0.0.5:5432 refused"), "connection error"),
    ],
)
async def test_transport_failures_are_categorised_without_leaking_details(
    exception: Exception, expected: str
) -> None:
    recorder = Recorder(exception)

    result = await send(
        "https://hooks.example.com/h", recorder, {"hooks.example.com": ["93.184.216.34"]}
    )

    assert not result.ok
    assert result.status_code is None
    assert result.error == expected
    assert "10.0.0.5" not in repr(result)


async def test_private_destinations_need_the_explicit_development_flag() -> None:
    mapping = {"receiver": ["172.18.0.5"]}
    blocked = Recorder(httpx.Response(200))
    allowed = Recorder(httpx.Response(200))

    denied = await send("http://receiver:8080/hook", blocked, mapping)
    permitted = await send("http://receiver:8080/hook", allowed, mapping, allow_private=True)

    assert denied.error == "destination not allowed"
    assert permitted.ok
    request = allowed.requests[0]
    assert request.url.host == "172.18.0.5"
    assert request.url.port == 8080
    assert request.headers["host"] == "receiver:8080"
