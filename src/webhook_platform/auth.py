import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from webhook_platform.config import Settings, get_settings
from webhook_platform.db import SessionDep
from webhook_platform.models import ApiKey, Tenant
from webhook_platform.security import API_KEY_PREFIX, hash_api_key

bearer = HTTPBearer(auto_error=False)
BearerDep = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid or missing credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_admin(credentials: BearerDep, settings: SettingsDep) -> None:
    expected = settings.admin_token.get_secret_value().encode()
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode(), expected
    ):
        raise _unauthorized()


async def get_current_tenant(credentials: BearerDep, session: SessionDep) -> Tenant:
    if credentials is None or not credentials.credentials.startswith(API_KEY_PREFIX):
        raise _unauthorized()

    statement = (
        select(Tenant)
        .join(ApiKey, ApiKey.tenant_id == Tenant.id)
        .where(
            ApiKey.key_hash == hash_api_key(credentials.credentials),
            ApiKey.revoked_at.is_(None),
        )
    )
    tenant = (await session.execute(statement)).scalar_one_or_none()
    if tenant is None:
        raise _unauthorized()
    return tenant


CurrentTenant = Annotated[Tenant, Depends(get_current_tenant)]
