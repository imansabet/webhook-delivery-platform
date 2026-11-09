import asyncio
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from webhook_platform.security import sign_webhook
from webhook_platform.urls import is_public_ip, validate_destination_url

Resolver = Callable[[str, int], Awaitable[list[str]]]

OVERALL_TIMEOUT_SECONDS = 15.0
USER_AGENT = "webhook-delivery-platform/0.1"


@dataclass(frozen=True)
class DeliveryResult:
    ok: bool
    status_code: int | None
    error: str | None
    duration_ms: int


async def resolve_host(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def create_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, connect=5.0),
        follow_redirects=False,
        trust_env=False,
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=0),
    )


async def send_webhook(
    client: httpx.AsyncClient,
    *,
    url: str,
    secret: str,
    message_id: str,
    body: bytes,
    allow_private: bool = False,
    resolver: Resolver = resolve_host,
    clock: Callable[[], float] = time.time,
) -> DeliveryResult:
    started = time.monotonic()

    def result(*, status_code: int | None = None, error: str | None = None) -> DeliveryResult:
        return DeliveryResult(
            ok=status_code is not None and 200 <= status_code < 300,
            status_code=status_code,
            error=error,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    try:
        validate_destination_url(url, allow_private=allow_private)
    except ValueError:
        return result(error="destination not allowed")

    target = httpx.URL(url)
    port = target.port or (443 if target.scheme == "https" else 80)
    try:
        addresses = await resolver(target.host, port)
    except OSError:
        return result(error="dns resolution failed")
    if not addresses:
        return result(error="dns resolution failed")
    if not allow_private and not all(is_public_ip(address) for address in addresses):
        return result(error="destination not allowed")

    timestamp = int(clock())
    request = client.build_request(
        "POST",
        target.copy_with(host=addresses[0]),
        content=body,
        headers={
            "Host": target.netloc.decode("ascii"),
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "webhook-id": message_id,
            "webhook-timestamp": str(timestamp),
            "webhook-signature": sign_webhook(secret, message_id, timestamp, body),
        },
        extensions={"sni_hostname": target.raw_host.decode("ascii")},
    )

    try:
        async with asyncio.timeout(OVERALL_TIMEOUT_SECONDS):
            response = await client.send(request, stream=True)
            await response.aclose()
    except (TimeoutError, httpx.TimeoutException):
        return result(error="timeout")
    except httpx.HTTPError:
        return result(error="connection error")

    return result(status_code=response.status_code)
