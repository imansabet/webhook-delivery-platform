import asyncio

import pytest
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.integration


async def test_new_event_then_replay_then_conflict(client, make_tenant, send_event, scalar):
    account = await make_tenant("acme")

    first = await send_event(account, "k1", payload={"order_id": 1})
    replay = await send_event(account, "k1", payload={"order_id": 1})
    conflict = await send_event(account, "k1", payload={"order_id": 2})

    assert first.status_code == 202
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    assert conflict.status_code == 409
    assert await scalar("select count(*) from events") == 1


async def test_idempotency_keys_are_scoped_per_tenant(make_tenant, send_event):
    first_tenant = await make_tenant("first")
    second_tenant = await make_tenant("second")

    first = await send_event(first_tenant, "same-key")
    second = await send_event(second_tenant, "same-key")

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] != second.json()["id"]


async def test_parallel_requests_with_the_same_key_create_one_event(
    make_tenant, send_event, scalar
):
    account = await make_tenant("acme")

    responses = await asyncio.gather(*(send_event(account, "race-1") for _ in range(20)))

    codes = sorted(response.status_code for response in responses)
    assert codes == [200] * 19 + [202]
    assert await scalar("select count(*) from events") == 1


async def test_event_fans_out_only_to_matching_endpoints_of_the_same_tenant(
    make_tenant, add_endpoint, send_event, scalar
):
    account = await make_tenant("acme")
    other = await make_tenant("other")
    await add_endpoint(account, "https://example.com/paid", ["order.paid"])
    await add_endpoint(account, "https://example.com/all", ["*"])
    await add_endpoint(account, "https://example.com/users", ["user.created"])
    await add_endpoint(other, "https://example.com/foreign", ["*"])

    async def deliveries_to(url: str) -> int:
        return await scalar(
            "select count(*) from deliveries d "
            "join endpoints e on e.id = d.endpoint_id where e.url = :url",
            url=url,
        )

    response = await send_event(account, "fan-1", "order.paid")

    assert response.status_code == 202
    assert await deliveries_to("https://example.com/paid") == 1
    assert await deliveries_to("https://example.com/all") == 1
    assert await deliveries_to("https://example.com/users") == 0
    assert await deliveries_to("https://example.com/foreign") == 0
    assert await scalar("select count(*) from deliveries where status = 'pending'") == 2


async def test_replayed_event_does_not_create_more_deliveries(
    make_tenant, add_endpoint, send_event, scalar
):
    account = await make_tenant("acme")
    await add_endpoint(account)

    await send_event(account, "fan-1")
    await send_event(account, "fan-1")

    assert await scalar("select count(*) from deliveries") == 1


async def test_failure_while_creating_deliveries_leaves_no_event_and_retry_succeeds(
    make_tenant, add_endpoint, send_event, execute, scalar
):
    account = await make_tenant("acme")
    await add_endpoint(account)
    await execute(
        "create function fail_delivery_insert() returns trigger as $$ "
        "begin raise exception 'simulated failure'; end; "
        "$$ language plpgsql"
    )
    await execute(
        "create trigger fail_deliveries before insert on deliveries "
        "for each row execute function fail_delivery_insert()"
    )
    try:
        with pytest.raises(DBAPIError):
            await send_event(account, "crash-1")
        assert await scalar("select count(*) from events") == 0
    finally:
        await execute("drop trigger fail_deliveries on deliveries")
        await execute("drop function fail_delivery_insert()")

    retry = await send_event(account, "crash-1")

    assert retry.status_code == 202
    assert await scalar("select count(*) from events") == 1
    assert await scalar("select count(*) from deliveries") == 1
