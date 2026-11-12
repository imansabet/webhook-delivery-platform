import asyncio
import contextlib
import json
import logging
import signal
import uuid
from collections.abc import Awaitable
from typing import Any, Protocol

from aiokafka import AIOKafkaProducer
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from webhook_platform.config import get_relay_settings
from webhook_platform.db import create_engine, create_sessionmaker
from webhook_platform.models import Delivery

logger = logging.getLogger("webhook_platform.relay")

ERROR_BACKOFF_SECONDS = 5.0


class Producer(Protocol):
    async def send(self, topic: str, *, key: bytes, value: bytes) -> Awaitable[Any]: ...


def _message(delivery_id: uuid.UUID, event_id: uuid.UUID, endpoint_id: uuid.UUID) -> bytes:
    body = {
        "delivery_id": str(delivery_id),
        "event_id": str(event_id),
        "endpoint_id": str(endpoint_id),
    }
    return json.dumps(body, separators=(",", ":")).encode()


async def publish_batch(
    session: AsyncSession, producer: Producer, *, topic: str, batch_size: int
) -> int:
    rows = (
        await session.execute(
            select(Delivery.id, Delivery.event_id, Delivery.endpoint_id)
            .where(
                Delivery.published_at.is_(None),
                or_(
                    Delivery.next_attempt_at.is_(None),
                    Delivery.next_attempt_at <= func.now(),
                ),
            )
            .order_by(Delivery.created_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
    ).all()
    if not rows:
        return 0

    acknowledgements = [
        await producer.send(
            topic,
            key=str(row.endpoint_id).encode(),
            value=_message(row.id, row.event_id, row.endpoint_id),
        )
        for row in rows
    ]
    await asyncio.gather(*acknowledgements)

    await session.execute(
        update(Delivery)
        .where(Delivery.id.in_([row.id for row in rows]))
        .values(published_at=func.now())
    )
    await session.commit()
    return len(rows)


async def run_relay(
    sessionmaker: async_sessionmaker[AsyncSession],
    producer: Producer,
    *,
    topic: str,
    batch_size: int,
    poll_interval: float,
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        published = 0
        wait = poll_interval
        try:
            async with sessionmaker() as session:
                published = await publish_batch(
                    session, producer, topic=topic, batch_size=batch_size
                )
            if published:
                logger.info("published %d deliveries", published)
        except Exception:
            logger.exception("relay iteration failed, will retry")
            wait = ERROR_BACKOFF_SECONDS

        if published < batch_size:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=wait)


async def main() -> None:
    settings = get_relay_settings()
    engine = create_engine(settings.database_url.get_secret_value())
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        acks="all",
        enable_idempotence=True,
        request_timeout_ms=10_000,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)

    await producer.start()
    logger.info("relay started, topic=%s", settings.deliveries_topic)
    try:
        await run_relay(
            create_sessionmaker(engine),
            producer,
            topic=settings.deliveries_topic,
            batch_size=settings.relay_batch_size,
            poll_interval=settings.relay_poll_interval_seconds,
            stop=stop,
        )
    finally:
        await producer.stop()
        await engine.dispose()
        logger.info("relay stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())
