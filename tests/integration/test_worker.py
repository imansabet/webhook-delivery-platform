import asyncio
import json
import uuid

import pytest

from webhook_platform.sender import DeliveryResult
from webhook_platform.worker import handle_batch, handle_message, process_delivery

pytestmark = pytest.mark.integration

OK = DeliveryResult(ok=True, status_code=200, error=None, duration_ms=12)
SERVER_ERROR = DeliveryResult(ok=False, status_code=500, error=None, duration_ms=30)


class FakeSend:
    def __init__(self, result: DeliveryResult | Exception = OK, delay: float = 0.0) -> None:
        self.result = result
        self.delay = delay
        self.calls: list[dict] = []
        self.active = 0
        self.max_active = 0

    async def __call__(self, client, **kwargs) -> DeliveryResult:
        self.calls.append(kwargs)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if isinstance(self.result, Exception):
                raise self.result
            return self.result
        finally:
            self.active -= 1


async def run(sessionmaker, send, delivery_id) -> str:
    async with sessionmaker() as session:
        return await process_delivery(session, None, delivery_id, allow_private=False, send=send)


async def prepare(make_tenant, add_endpoint, send_event, *, payload=None, count=1):
    account = await make_tenant("acme")
    endpoint = await add_endpoint(account, "https://hooks.example.com/in", ["order.paid"])
    for index in range(count):
        await send_event(account, f"k{index}", payload=payload)
    return endpoint


async def test_successful_delivery_is_sent_and_recorded(
    make_tenant, add_endpoint, send_event, sessionmaker, scalar, column
):
    endpoint = await prepare(make_tenant, add_endpoint, send_event, payload={"order_id": 7})
    [delivery_id] = await column("select id from deliveries")
    send = FakeSend()

    outcome = await run(sessionmaker, send, delivery_id)

    event_id = await scalar("select id from events")
    call = send.calls[0]
    body = json.loads(call["body"])
    assert outcome == "succeeded"
    assert call["url"] == "https://hooks.example.com/in"
    assert call["secret"] == endpoint["secret"]
    assert call["message_id"] == str(event_id)
    assert body == {
        "id": str(event_id),
        "type": "order.paid",
        "created_at": body["created_at"],
        "data": {"order_id": 7},
    }
    assert await scalar("select status from deliveries") == "succeeded"
    assert await scalar("select attempt_number from delivery_attempts") == 1
    assert await scalar("select status_code from delivery_attempts") == 200


async def test_failed_delivery_records_the_response(
    make_tenant, add_endpoint, send_event, sessionmaker, scalar, column
):
    await prepare(make_tenant, add_endpoint, send_event)
    [delivery_id] = await column("select id from deliveries")

    outcome = await run(sessionmaker, FakeSend(SERVER_ERROR), delivery_id)

    assert outcome == "failed"
    assert await scalar("select status from deliveries") == "failed"
    assert await scalar("select status_code from delivery_attempts") == 500
    assert await scalar("select error from delivery_attempts") is None


async def test_processing_the_same_delivery_twice_sends_only_once(
    make_tenant, add_endpoint, send_event, sessionmaker, scalar, column
):
    await prepare(make_tenant, add_endpoint, send_event)
    [delivery_id] = await column("select id from deliveries")
    send = FakeSend()

    first = await run(sessionmaker, send, delivery_id)
    second = await run(sessionmaker, send, delivery_id)

    assert (first, second) == ("succeeded", "skipped")
    assert len(send.calls) == 1
    assert await scalar("select count(*) from delivery_attempts") == 1


async def test_concurrent_duplicates_are_serialised_by_the_row_lock(
    make_tenant, add_endpoint, send_event, sessionmaker, column
):
    await prepare(make_tenant, add_endpoint, send_event)
    [delivery_id] = await column("select id from deliveries")
    send = FakeSend(delay=0.2)

    outcomes = await asyncio.gather(
        run(sessionmaker, send, delivery_id), run(sessionmaker, send, delivery_id)
    )

    assert sorted(outcomes) == ["skipped", "succeeded"]
    assert len(send.calls) == 1


async def test_unknown_delivery_is_reported_missing(sessionmaker) -> None:
    send = FakeSend()

    assert await run(sessionmaker, send, uuid.uuid4()) == "missing"
    assert send.calls == []


@pytest.mark.parametrize(
    "value",
    [b"not json", b"[]", b"null", b"{}", b'{"delivery_id": "nope"}', b'{"delivery_id": 5}'],
)
async def test_malformed_messages_are_skipped_without_sending(sessionmaker, value) -> None:
    send = FakeSend()

    outcome = await handle_message(sessionmaker, None, value, allow_private=False, send=send)

    assert outcome == "malformed"
    assert send.calls == []


async def test_infrastructure_errors_leave_the_delivery_pending(
    make_tenant, add_endpoint, send_event, sessionmaker, scalar, column
):
    await prepare(make_tenant, add_endpoint, send_event)
    [delivery_id] = await column("select id from deliveries")

    with pytest.raises(RuntimeError):
        await run(sessionmaker, FakeSend(RuntimeError("database went away")), delivery_id)

    assert await scalar("select status from deliveries") == "pending"
    assert await scalar("select count(*) from delivery_attempts") == 0


async def test_body_keeps_non_ascii_text_readable(
    make_tenant, add_endpoint, send_event, sessionmaker, column
):
    await prepare(make_tenant, add_endpoint, send_event, payload={"name": "علی"})
    [delivery_id] = await column("select id from deliveries")
    send = FakeSend()

    await run(sessionmaker, send, delivery_id)

    text = send.calls[0]["body"].decode("utf-8")
    assert "علی" in text
    assert "\\u" not in text


async def test_batch_respects_the_concurrency_limit(
    make_tenant, add_endpoint, send_event, sessionmaker, scalar, column
):
    await prepare(make_tenant, add_endpoint, send_event, count=5)
    ids = await column("select id from deliveries")
    values = [json.dumps({"delivery_id": str(delivery_id)}).encode() for delivery_id in ids]
    send = FakeSend(delay=0.1)

    outcomes = await handle_batch(
        values, sessionmaker, None, concurrency=2, allow_private=False, send=send
    )

    assert outcomes == ["succeeded"] * 5
    assert send.max_active == 2
    assert await scalar("select count(*) from deliveries where status = 'succeeded'") == 5
