import asyncio
import uuid

import pytest

pytestmark = pytest.mark.integration


async def fail_all_with_two_attempts(execute) -> None:
    await execute("update deliveries set status = 'failed'")
    await execute(
        "insert into delivery_attempts "
        "(delivery_id, attempt_number, status_code, error, duration_ms) "
        "select id, attempt, 503, null, 20 "
        "from deliveries, generate_series(1, 2) as attempt"
    )


async def test_owner_can_read_event_deliveries_and_attempt_log(
    client, make_tenant, add_endpoint, send_event, execute
):
    account = await make_tenant("acme")
    endpoint = await add_endpoint(account, "https://hooks.example.com/in", ["order.paid"])
    event = (await send_event(account, "k1")).json()

    deliveries = (
        await client.get(f"/events/{event['id']}/deliveries", headers=account.headers)
    ).json()
    delivery_path = f"/deliveries/{deliveries[0]['id']}"
    pending = await client.get(delivery_path, headers=account.headers)
    await fail_all_with_two_attempts(execute)
    failed = await client.get(delivery_path, headers=account.headers)
    event_view = await client.get(f"/events/{event['id']}", headers=account.headers)

    assert len(deliveries) == 1
    assert deliveries[0]["endpoint_id"] == endpoint["id"]
    assert deliveries[0]["status"] == "pending"
    assert pending.json()["attempts"] == []
    assert failed.json()["status"] == "failed"
    assert [item["attempt_number"] for item in failed.json()["attempts"]] == [1, 2]
    assert failed.json()["attempts"][0]["status_code"] == 503
    assert event_view.json()["payload"] == {"n": 1}
    assert "secret" not in str(failed.json())


async def test_delivery_list_filters_by_status_and_endpoint(
    client, make_tenant, add_endpoint, send_event, execute
):
    account = await make_tenant("acme")
    first = await add_endpoint(account, "https://example.com/a")
    second = await add_endpoint(account, "https://example.com/b")
    await send_event(account, "k1")
    await execute(
        "update deliveries set status = 'failed' where endpoint_id::text = :id", id=first["id"]
    )

    everything = await client.get("/deliveries", headers=account.headers)
    failed = await client.get("/deliveries?status=failed", headers=account.headers)
    only_second = await client.get(
        f"/deliveries?endpoint_id={second['id']}", headers=account.headers
    )

    assert len(everything.json()) == 2
    assert [item["endpoint_id"] for item in failed.json()] == [first["id"]]
    assert [item["status"] for item in only_second.json()] == ["pending"]
    assert (
        await client.get("/deliveries?status=bogus", headers=account.headers)
    ).status_code == 422
    assert (await client.get("/deliveries?limit=0", headers=account.headers)).status_code == 422


async def test_other_tenants_cannot_see_or_replay_deliveries(
    client, make_tenant, add_endpoint, send_event, execute
):
    owner = await make_tenant("owner")
    intruder = await make_tenant("intruder")
    await add_endpoint(owner)
    event = (await send_event(owner, "k1")).json()
    await fail_all_with_two_attempts(execute)
    [delivery] = (await client.get("/deliveries", headers=owner.headers)).json()
    delivery_path = f"/deliveries/{delivery['id']}"

    responses = [
        await client.get(f"/events/{event['id']}", headers=intruder.headers),
        await client.get(f"/events/{event['id']}/deliveries", headers=intruder.headers),
        await client.get(delivery_path, headers=intruder.headers),
        await client.post(f"{delivery_path}/replay", headers=intruder.headers),
    ]

    assert [response.status_code for response in responses] == [404, 404, 404, 404]
    assert (await client.get("/deliveries", headers=intruder.headers)).json() == []
    assert (await client.get(delivery_path, headers=owner.headers)).json()["status"] == "failed"


async def test_replay_requeues_only_failed_deliveries(
    client, make_tenant, add_endpoint, send_event, execute, scalar
):
    account = await make_tenant("acme")
    await add_endpoint(account)
    await send_event(account, "k1")
    [delivery] = (await client.get("/deliveries", headers=account.headers)).json()
    path = f"/deliveries/{delivery['id']}/replay"

    not_failed = await client.post(path, headers=account.headers)
    await fail_all_with_two_attempts(execute)
    await execute("update deliveries set published_at = now(), next_attempt_at = now()")
    replayed = await client.post(path, headers=account.headers)
    again = await client.post(path, headers=account.headers)
    unknown = await client.post(f"/deliveries/{uuid.uuid4()}/replay", headers=account.headers)

    assert not_failed.status_code == 409
    assert replayed.status_code == 202
    assert replayed.json()["status"] == "pending"
    assert replayed.json()["next_attempt_at"] is None
    assert again.status_code == 409
    assert unknown.status_code == 404
    assert await scalar("select published_at from deliveries") is None
    assert await scalar("select cycle_start_attempt from deliveries") == 2
    assert await scalar("select count(*) from delivery_attempts") == 2


async def test_concurrent_replays_requeue_only_once(
    client, make_tenant, add_endpoint, send_event, execute
):
    account = await make_tenant("acme")
    await add_endpoint(account)
    await send_event(account, "k1")
    await fail_all_with_two_attempts(execute)
    [delivery] = (await client.get("/deliveries", headers=account.headers)).json()
    path = f"/deliveries/{delivery['id']}/replay"

    responses = await asyncio.gather(
        *(client.post(path, headers=account.headers) for _ in range(5))
    )

    assert sorted(response.status_code for response in responses) == [202, 409, 409, 409, 409]
