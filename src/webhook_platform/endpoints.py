import uuid
from collections.abc import Sequence

from fastapi import APIRouter, HTTPException, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from webhook_platform.auth import CurrentTenant, SettingsDep
from webhook_platform.db import SessionDep
from webhook_platform.models import Endpoint, Tenant
from webhook_platform.pagination import Limit, Offset
from webhook_platform.schemas import EndpointCreate, EndpointCreated, EndpointRead
from webhook_platform.security import generate_webhook_secret
from webhook_platform.urls import validate_destination_url

router = APIRouter(prefix="/endpoints", tags=["endpoints"])
MAX_ENDPOINTS_PER_TENANT = 20


async def _get_owned_endpoint(
    session: AsyncSession, tenant: Tenant, endpoint_id: uuid.UUID
) -> Endpoint:
    statement = select(Endpoint).where(Endpoint.id == endpoint_id, Endpoint.tenant_id == tenant.id)
    endpoint = (await session.execute(statement)).scalar_one_or_none()
    if endpoint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="endpoint not found")
    return endpoint


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_endpoint(
    payload: EndpointCreate, tenant: CurrentTenant, session: SessionDep, settings: SettingsDep
) -> EndpointCreated:
    try:
        validate_destination_url(payload.url, allow_private=settings.allow_private_destinations)
    except ValueError as exc:
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("body", "url"),
                    "msg": str(exc),
                    "input": payload.url,
                }
            ]
        ) from exc

    count = (
        await session.execute(
            select(func.count()).select_from(Endpoint).where(Endpoint.tenant_id == tenant.id)
        )
    ).scalar_one()
    if count >= MAX_ENDPOINTS_PER_TENANT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"endpoint limit reached ({MAX_ENDPOINTS_PER_TENANT})",
        )
    endpoint = Endpoint(
        tenant_id=tenant.id,
        url=payload.url,
        event_types=payload.event_types,
        secret=generate_webhook_secret(),
    )
    session.add(endpoint)
    await session.commit()
    await session.refresh(endpoint)
    return EndpointCreated.model_validate(endpoint)


@router.get("", response_model=list[EndpointRead])
async def list_endpoints(
    tenant: CurrentTenant,
    session: SessionDep,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Sequence[Endpoint]:
    statement = (
        select(Endpoint)
        .where(Endpoint.tenant_id == tenant.id)
        .order_by(Endpoint.created_at.desc(), Endpoint.id)
        .limit(limit)
        .offset(offset)
    )
    return (await session.execute(statement)).scalars().all()


@router.get("/{endpoint_id}", response_model=EndpointRead)
async def read_endpoint(
    endpoint_id: uuid.UUID, tenant: CurrentTenant, session: SessionDep
) -> Endpoint:
    return await _get_owned_endpoint(session, tenant, endpoint_id)


@router.delete("/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_endpoint(
    endpoint_id: uuid.UUID, tenant: CurrentTenant, session: SessionDep
) -> None:
    endpoint = await _get_owned_endpoint(session, tenant, endpoint_id)
    await session.delete(endpoint)
    await session.commit()
