from fastapi import APIRouter, Depends, status

from webhook_platform.auth import CurrentTenant, require_admin
from webhook_platform.db import SessionDep
from webhook_platform.models import ApiKey, Tenant
from webhook_platform.schemas import TenantCreate, TenantCreated, TenantRead
from webhook_platform.security import display_prefix, generate_api_key, hash_api_key

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_tenant(payload: TenantCreate, session: SessionDep) -> TenantCreated:
    tenant = Tenant(name=payload.name)
    session.add(tenant)
    await session.flush()

    api_key = generate_api_key()
    session.add(
        ApiKey(
            tenant_id=tenant.id,
            key_prefix=display_prefix(api_key),
            key_hash=hash_api_key(api_key),
        )
    )
    await session.commit()
    await session.refresh(tenant)

    return TenantCreated(tenant=TenantRead.model_validate(tenant), api_key=api_key)


@router.get("/me", response_model=TenantRead)
async def read_me(tenant: CurrentTenant) -> Tenant:
    return tenant
