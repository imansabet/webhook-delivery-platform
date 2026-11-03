from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from webhook_platform.auth import CurrentTenant
from webhook_platform.db import SessionDep
from webhook_platform.models import Event
from webhook_platform.schemas import EventCreate, EventRead

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
