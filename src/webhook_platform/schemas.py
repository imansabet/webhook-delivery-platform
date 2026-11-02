import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TenantCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)


class TenantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime


class TenantCreated(BaseModel):
    tenant: TenantRead
    api_key: str
