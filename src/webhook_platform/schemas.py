import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from webhook_platform.urls import MAX_URL_LENGTH, validate_destination_url


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


class EndpointCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    url: str = Field(max_length=MAX_URL_LENGTH)

    @field_validator("url")
    @classmethod
    def check_url(cls, value: str) -> str:
        return validate_destination_url(value)


class EndpointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    created_at: datetime


class EndpointCreated(EndpointRead):
    secret: str
