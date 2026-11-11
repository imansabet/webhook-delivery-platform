import asyncio
import contextlib
import json
import logging
import signal
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from aiokafka import AIOKafkaConsumer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from webhook_platform.config import WorkerSettings, get_worker_settings
from webhook_platform.db import create_engine, create_sessionmaker
from webhook_platform.models import (
    Delivery,
    DeliveryAttempt,
    DeliveryStatus,
    Endpoint,
    Event,
)
from webhook_platform.sender import DeliveryResult, create_http_client, send_webhook

logger = logging.getLogger("webhook_platform.worker")

ERROR_BACKOFF_SECONDS = 5.0

SendFunction = Callable[..., Awaitable[DeliveryResult]]


def build_body(event: Event) -> bytes:
    envelope = {
        "id": str(event.id),
        "type": event.type,
        "created_at": event.created_at.isoformat(),
        "data": event.payload,
    }
    return json.dumps(envelope, separators=(",", ":"), ensure_ascii=False).encode()


async def process_delivery(
    session: AsyncSession,
    client: httpx.AsyncClient | None,
    delivery_id: uuid.UUID,
    *,
    allow_private: bool,
    send: SendFunction = send_webhook,
) -> str:
    row = (
        await session.execute(
            select(Delivery, Event, Endpoint)
            .join(Event, Event.id == Delivery.event_id)
            .join(Endpoint, Endpoint.id == Delivery.endpoint_id)
            .where(Delivery.id == delivery_id)
            .with_for_update(of=Delivery)
        )
    ).one_or_none()
    if row is None:
        return "missing"

    delivery, event, endpoint = row
    if delivery.status != DeliveryStatus.PENDING:
        return "skipped"

    result = await send(
        client,
        url=endpoint.url,
        secret=endpoint.secret,
        message_id=str(event.id),
        body=build_body(event),
        allow_private=allow_private,
    )

    previous_attempts = (
        await session.execute(
            select(func.count())
            .select_from(DeliveryAttempt)
            .where(DeliveryAttempt.delivery_id == delivery.id)
        )
    ).scalar_one()
    session.add(
        DeliveryAttempt(
            delivery_id=delivery.id,
            attempt_number=previous_attempts + 1,
            status_code=result.status_code,
            error=result.error,
            duration_ms=result.duration_ms,
        )
    )
    outcome = DeliveryStatus.SUCCEEDED if result.ok else DeliveryStatus.FAILED
    delivery.status = outcome.value
    await session.commit()
    return outcome.value


async def handle_message(
    sessionmaker: async_sessionmaker[AsyncSession],
    client: httpx.AsyncClient | None,
    value: bytes,
    *,
    allow_private: bool,
    send: SendFunction = send_webhook,
) -> str:
    try:
        delivery_id = uuid.UUID(str(json.loads(value)["delivery_id"]))
    except (ValueError, KeyError, TypeError):
        logger.error("skipping malformed message: %r", value[:200])
        return "malformed"

    async with sessionmaker() as session:
        outcome = await process_delivery(
            session, client, delivery_id, allow_private=allow_private, send=send
        )
    logger.info("delivery %s: %s", delivery_id, outcome)
    return outcome


async def handle_batch(
    values: list[bytes],
    sessionmaker: async_sessionmaker[AsyncSession],
    client: httpx.AsyncClient | None,
    *,
    concurrency: int,
    allow_private: bool,
    send: SendFunction = send_webhook,
) -> list[str]:
    semaphore = asyncio.Semaphore(concurrency)

    async def handle_one(value: bytes) -> str:
        async with semaphore:
            return await handle_message(
                sessionmaker, client, value, allow_private=allow_private, send=send
            )

    return list(await asyncio.gather(*(handle_one(value) for value in values)))


async def run_worker(
    consumer: Any,
    sessionmaker: async_sessionmaker[AsyncSession],
    client: httpx.AsyncClient,
    *,
    settings: WorkerSettings,
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        batches = await consumer.getmany(timeout_ms=1000, max_records=settings.worker_batch_size)
        if not batches:
            continue

        values = [record.value for records in batches.values() for record in records]
        try:
            outcomes = await handle_batch(
                values,
                sessionmaker,
                client,
                concurrency=settings.worker_concurrency,
                allow_private=settings.allow_private_destinations,
            )
            await consumer.commit()
            logger.info("batch done: %s", dict(Counter(outcomes)))
        except Exception:
            logger.exception("batch failed, rewinding to retry")
            for partition, records in batches.items():
                consumer.seek(partition, records[0].offset)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=ERROR_BACKOFF_SECONDS)


async def main() -> None:
    settings = get_worker_settings()
    if settings.allow_private_destinations:
        logger.warning(
            "ALLOW_PRIVATE_DESTINATIONS is enabled: SSRF protection is relaxed. "
            "Never use this in production."
        )

    engine = create_engine(
        settings.database_url.get_secret_value(), pool_size=settings.worker_concurrency
    )
    consumer = AIOKafkaConsumer(
        settings.deliveries_topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.consumer_group,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)

    async with create_http_client() as client:
        await consumer.start()
        logger.info(
            "worker started, topic=%s group=%s concurrency=%d",
            settings.deliveries_topic,
            settings.consumer_group,
            settings.worker_concurrency,
        )
        try:
            await run_worker(
                consumer, create_sessionmaker(engine), client, settings=settings, stop=stop
            )
        finally:
            await consumer.stop()
            await engine.dispose()
            logger.info("worker stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())
