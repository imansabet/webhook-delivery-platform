import json
import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from webhook_platform.urls import MAX_URL_LENGTH

MAX_PAYLOAD_BYTES = 262_144

EventType = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$", max_length=100),
]

Subscription = Annotated[
    str,
    StringConstraints(pattern=r"^(\*|[a-z][a-z0-9_]*(\.[a-z0-9_]+)*)$", max_length=100),
]


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
    event_types: list[Subscription] = Field(min_length=1, max_length=20)

    @field_validator("event_types")
    @classmethod
    def duplicate(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class EndpointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    event_types: list[str]
    created_at: datetime


class EndpointCreated(EndpointRead):
    secret: str


class EventCreate(BaseModel):
    type: EventType
    payload: dict[str, Any]

    @field_validator("payload")
    @classmethod
    def limit_payload_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        size = len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())
        if size > MAX_PAYLOAD_BYTES:
            raise ValueError(f"payload must be at most {MAX_PAYLOAD_BYTES} bytes")
        return value


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    payload: dict[str, Any]
    created_at: datetime
