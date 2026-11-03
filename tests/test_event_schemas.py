import pytest
from pydantic import ValidationError

from webhook_platform.schemas import EndpointCreate, EventCreate


def test_valid_event_is_accepted() -> None:
    event = EventCreate(type="order.paid", payload={"order_id": 123})

    assert event.type == "order.paid"


@pytest.mark.parametrize(
    "event_type",
    ["", "Order.Paid", "order paid", ".order", "order.", "1order", "a" * 101],
)
def test_invalid_event_types_are_rejected(event_type: str) -> None:
    with pytest.raises(ValidationError):
        EventCreate(type=event_type, payload={})


@pytest.mark.parametrize("payload", [[], "text", 5, None])
def test_payload_must_be_a_json_object(payload: object) -> None:
    with pytest.raises(ValidationError):
        EventCreate(type="order.paid", payload=payload)  # type: ignore[arg-type]


def test_oversized_payload_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EventCreate(type="order.paid", payload={"blob": "x" * 300_000})


def test_endpoint_event_types_are_deduplicated_and_required() -> None:
    endpoint = EndpointCreate(url="https://example.com/h", event_types=["a.b", "a.b", "*"])

    assert endpoint.event_types == ["a.b", "*"]
    with pytest.raises(ValidationError):
        EndpointCreate(url="https://example.com/h", event_types=[])
    with pytest.raises(ValidationError):
        EndpointCreate(url="https://example.com/h", event_types=["Bad Type"])
