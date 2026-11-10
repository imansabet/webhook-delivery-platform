import asyncio
import logging
import time
from collections import deque
from typing import Annotated, Any

from fastapi import FastAPI, Path, Request, Response
from pydantic import BaseModel, field_validator

from webhook_platform.security import validate_webhook_secret, verify_webhook

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("webhook_platform.receiver")


app = FastAPI(title="webhook-dev-receiver")

secrets_registry: list[str] = []
received: deque[dict[str, Any]] = deque(maxlen=100)
seen_ids: set[str] = set()


class SecretIn(BaseModel):
    secret: str

    @field_validator("secret")
    @classmethod
    def must_be_a_valid_secret(cls, value: str) -> str:
        if not validate_webhook_secret(value):
            raise ValueError("invalid webhook secret")
        return value


async def record_request(request: Request) -> bool:
    body = await request.body()
    message_id = request.headers.get("webhook-id", "")
    timestamp = request.headers.get("webhook-timestamp", "")
    signature = request.headers.get("webhook-signature", "")

    verified = any(
        verify_webhook(secret, message_id, timestamp, signature, body, now=time.time())
        for secret in secrets_registry
    )
    duplicate = verified and message_id in seen_ids
    if verified:
        seen_ids.add(message_id)

    received.append(
        {
            "path": request.url.path,
            "webhook_id": message_id,
            "verified": verified,
            "duplicate": duplicate,
            "body": body.decode(errors="replace")[:2000],
        }
    )
    logger.info(
        "%s id=%s verified=%s duplicate=%s", request.url.path, message_id, verified, duplicate
    )
    return verified


@app.post("/hook")
async def hook(request: Request) -> Response:
    verified = await record_request(request)
    return Response(status_code=200 if verified else 401)


@app.post("/slow/{seconds}")
async def slow(request: Request, seconds: Annotated[float, Path(ge=0, le=30)]) -> Response:
    await record_request(request)
    await asyncio.sleep(seconds)
    return Response(status_code=200)


@app.post("/status/{code}")
async def status(request: Request, code: Annotated[int, Path(ge=200, le=599)]) -> Response:
    await record_request(request)
    return Response(status_code=code)


@app.put("/dev/secret")
async def register_secret(body: SecretIn) -> dict[str, int]:
    secrets_registry.append(body.secret)
    return {"registered": len(secrets_registry)}


@app.get("/dev/received")
async def list_received() -> list[dict[str, Any]]:
    return list(received)


@app.delete("/dev/received", status_code=204)
async def clear_received() -> None:
    received.clear()
    seen_ids.clear()
