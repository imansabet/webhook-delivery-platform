import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from webhook_platform.auth import CurrentTenant
from webhook_platform.db import SessionDep
from webhook_platform.models import Endpoint, Tenant
from webhook_platform.schemas import EndpointCreate, EndpointCreated, EndpointRead
from webhook_platform.security import generate_webhook_secret

router = APIRouter(prefix="/endpoints", tags=["endpoints"])


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
    payload: EndpointCreate, tenant: CurrentTenant, session: SessionDep
) -> EndpointCreated:
    endpoint = Endpoint(tenant_id=tenant.id, url=payload.url, secret=generate_webhook_secret())
    session.add(endpoint)
    await session.commit()
    await session.refresh(endpoint)
    return EndpointCreated.model_validate(endpoint)


@router.get("", response_model=list[EndpointRead])
async def list_endpoints(
    tenant: CurrentTenant,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
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
