import asyncio
import json

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from webhook_platform.relay import publish_batch

pytestmark = pytest.mark.integration


class FakeProducer:
    def __init__(self, *, fail: bool = False, delay: float = 0.0) -> None:
        self.sent: list[tuple[str, bytes, bytes]] = []
        self.fail = fail
        self.delay = delay

    async def send(self, topic: str, *, key: bytes, value: bytes) -> asyncio.Future[None]:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("kafka is down")
        self.sent.append((topic, key, value))
        acknowledgement: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        acknowledgement.set_result(None)
        return acknowledgement


@pytest.fixture
def sessionmaker(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


async def run_once(sessionmaker, producer, batch_size: int = 100) -> int:
    async with sessionmaker() as session:
        return await publish_batch(session, producer, topic="deliveries", batch_size=batch_size)


async def test_pending_deliveries_are_published_with_endpoint_key_and_marked(
    make_tenant, add_endpoint, send_event, sessionmaker, scalar
):
    account = await make_tenant("acme")
    endpoint = await add_endpoint(account)
    for index in range(3):
        await send_event(account, f"k{index}")
    producer = FakeProducer()

    published = await run_once(sessionmaker, producer)

    assert published == 3
    assert {key for _, key, _ in producer.sent} == {endpoint["id"].encode()}
    message = json.loads(producer.sent[0][2])
    assert set(message) == {"delivery_id", "event_id", "endpoint_id"}
    assert message["endpoint_id"] == endpoint["id"]
    assert await scalar("select count(*) from deliveries where published_at is null") == 0
    assert await run_once(sessionmaker, producer) == 0


async def test_batch_size_limits_each_round(make_tenant, add_endpoint, send_event, sessionmaker):
    account = await make_tenant("acme")
    await add_endpoint(account)
    for index in range(3):
        await send_event(account, f"k{index}")
    producer = FakeProducer()

    assert await run_once(sessionmaker, producer, batch_size=2) == 2
    assert await run_once(sessionmaker, producer, batch_size=2) == 1


async def test_failed_publish_leaves_deliveries_unpublished_so_they_are_retried(
    make_tenant, add_endpoint, send_event, sessionmaker, scalar
):
    account = await make_tenant("acme")
    await add_endpoint(account)
    await send_event(account, "k1")

    with pytest.raises(RuntimeError):
        await run_once(sessionmaker, FakeProducer(fail=True))

    assert await scalar("select count(*) from deliveries where published_at is null") == 1
    assert await run_once(sessionmaker, FakeProducer()) == 1


async def test_concurrent_relays_never_publish_the_same_delivery(
    make_tenant, add_endpoint, send_event, sessionmaker
):
    account = await make_tenant("acme")
    await add_endpoint(account)
    for index in range(10):
        await send_event(account, f"k{index}")
    first, second = FakeProducer(delay=0.2), FakeProducer(delay=0.2)

    counts = await asyncio.gather(
        run_once(sessionmaker, first, batch_size=10),
        run_once(sessionmaker, second, batch_size=10),
    )

    assert sum(counts) == 10
    ids = [json.loads(value)["delivery_id"] for _, _, value in first.sent + second.sent]
    assert len(ids) == len(set(ids)) == 10
