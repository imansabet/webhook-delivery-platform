import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Response, status
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from webhook_platform.auth import CurrentTenant
from webhook_platform.db import SessionDep
from webhook_platform.models import Delivery, Endpoint, Event, Tenant
from webhook_platform.schemas import DeliveryRead, EventCreate, EventRead

router = APIRouter(prefix="/events", tags=["events"])


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=EventRead)
async def ingest_event(
    body: EventCreate,
    tenant: CurrentTenant,
    session: SessionDep,
    response: Response,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=255)],
) -> Event:
    insert_statement = (
        insert(Event)
        .values(
            tenant_id=tenant.id,
            type=body.type,
            payload=body.payload,
            idempotency_key=idempotency_key,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "idempotency_key"])
        .returning(Event)
    )
    created = (await session.execute(insert_statement)).scalar_one_or_none()
    if created is not None:
        endpoint_ids = (
            (
                await session.execute(
                    select(Endpoint.id).where(
                        Endpoint.tenant_id == tenant.id,
                        or_(
                            Endpoint.event_types.contains([body.type]),
                            Endpoint.event_types.contains(["*"]),
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        session.add_all(
            Delivery(event_id=created.id, endpoint_id=endpoint_id) for endpoint_id in endpoint_ids
        )
        await session.commit()
        return created
    existing = (
        await session.execute(
            select(Event).where(
                Event.tenant_id == tenant.id,
                Event.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one()
    if existing.type != body.type or existing.payload != body.payload:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="idempotency key was already used with a different request",
        )
    response.status_code = status.HTTP_200_OK
    return existing


async def get_owned_event(session: AsyncSession, tenant: Tenant, event_id: uuid.UUID) -> Event:
    event = (
        await session.execute(
            select(Event).where(Event.id == event_id, Event.tenant_id == tenant.id)
        )
    ).scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="event not found")
    return event


@router.get("/{event_id}", response_model=EventRead)
async def read_event(event_id: uuid.UUID, tenant: CurrentTenant, session: SessionDep) -> Event:
    return await get_owned_event(session, tenant, event_id)


@router.get("/{event_id}/deliveries", response_model=list[DeliveryRead])
async def list_event_deliveries(
    event_id: uuid.UUID, tenant: CurrentTenant, session: SessionDep
) -> Sequence[Delivery]:
    await get_owned_event(session, tenant, event_id)
    statement = (
        select(Delivery)
        .where(Delivery.event_id == event_id)
        .order_by(Delivery.created_at, Delivery.id)
    )
    return (await session.execute(statement)).scalars().all()
