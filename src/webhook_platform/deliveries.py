import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from webhook_platform.auth import CurrentTenant
from webhook_platform.db import SessionDep
from webhook_platform.models import (
    Delivery,
    DeliveryAttempt,
    DeliveryStatus,
    Event,
    Tenant,
)
from webhook_platform.pagination import Limit, Offset
from webhook_platform.schemas import DeliveryAttemptRead, DeliveryDetail, DeliveryRead

router = APIRouter(prefix="/deliveries", tags=["deliveries"])


def owned_deliveries(tenant: Tenant) -> Select[Delivery]:
    return (
        select(Delivery)
        .join(Event, Event.id == Delivery.event_id)
        .where(Event.tenant_id == tenant.id)
    )


async def get_owned_delivery(
    session: AsyncSession, tenant: Tenant, delivery_id: uuid.UUID, *, lock: bool = False
) -> Delivery:
    statement = owned_deliveries(tenant).where(Delivery.id == delivery_id)
    if lock:
        statement = statement.with_for_update(of=Delivery)
    delivery = (await session.execute(statement)).scalar_one_or_none()
    if delivery is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="delivery not found")
    return delivery


@router.get("", response_model=list[DeliveryRead])
async def list_deliveries(
    tenant: CurrentTenant,
    session: SessionDep,
    limit: Limit = 50,
    offset: Offset = 0,
    delivery_status: Annotated[DeliveryStatus | None, Query(alias="status")] = None,
    endpoint_id: uuid.UUID | None = None,
) -> Sequence[Delivery]:
    statement = owned_deliveries(tenant)
    if delivery_status is not None:
        statement = statement.where(Delivery.status == delivery_status.value)
    if endpoint_id is not None:
        statement = statement.where(Delivery.endpoint_id == endpoint_id)
    statement = (
        statement.order_by(Delivery.created_at.desc(), Delivery.id)
        .limit(limit)
        .offset(offset)
    )
    return (await session.execute(statement)).scalars().all()


@router.get("/{delivery_id}", response_model=DeliveryDetail)
async def read_delivery(
    delivery_id: uuid.UUID, tenant: CurrentTenant, session: SessionDep
) -> DeliveryDetail:
    delivery = await get_owned_delivery(session, tenant, delivery_id)
    attempts = (
        (
            await session.execute(
                select(DeliveryAttempt)
                .where(DeliveryAttempt.delivery_id == delivery.id)
                .order_by(DeliveryAttempt.attempt_number)
            )
        )
        .scalars()
        .all()
    )
    return DeliveryDetail(
        **DeliveryRead.model_validate(delivery).model_dump(),
        attempts=[DeliveryAttemptRead.model_validate(attempt) for attempt in attempts],
    )


@router.post(
    "/{delivery_id}/replay",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DeliveryRead,
)
async def replay_delivery(
    delivery_id: uuid.UUID, tenant: CurrentTenant, session: SessionDep
) -> Delivery:
    delivery = await get_owned_delivery(session, tenant, delivery_id, lock=True)
    if delivery.status != DeliveryStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="only failed deliveries can be replayed",
        )

    attempts_so_far = (
        await session.execute(
            select(func.count())
            .select_from(DeliveryAttempt)
            .where(DeliveryAttempt.delivery_id == delivery.id)
        )
    ).scalar_one()

    delivery.status = DeliveryStatus.PENDING.value
    delivery.published_at = None
    delivery.next_attempt_at = None
    delivery.cycle_start_attempt = attempts_so_far
    await session.commit()
    return delivery
