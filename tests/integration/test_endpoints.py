import pytest

pytestmark = pytest.mark.integration


async def test_secret_is_returned_only_on_creation(client, make_tenant, add_endpoint):
    account = await make_tenant("acme")
    created = await add_endpoint(account, event_types=["order.paid"])

    listed = await client.get("/endpoints", headers=account.headers)
    fetched = await client.get(f"/endpoints/{created['id']}", headers=account.headers)

    assert created["secret"].startswith("whsec_")
    assert "secret" not in fetched.json()
    assert all("secret" not in item for item in listed.json())
    assert listed.json()[0]["event_types"] == ["order.paid"]


async def test_tenants_cannot_see_or_delete_each_others_endpoints(
    client, make_tenant, add_endpoint, scalar
):
    owner = await make_tenant("owner")
    intruder = await make_tenant("intruder")
    endpoint = await add_endpoint(owner)
    path = f"/endpoints/{endpoint['id']}"

    assert (await client.get(path, headers=intruder.headers)).status_code == 404
    assert (await client.delete(path, headers=intruder.headers)).status_code == 404
    assert (await client.get("/endpoints", headers=intruder.headers)).json() == []
    assert await scalar("select count(*) from endpoints") == 1


async def test_endpoint_limit_is_enforced_per_tenant(client, make_tenant, add_endpoint):
    account = await make_tenant("acme")
    for index in range(20):
        await add_endpoint(account, url=f"https://example.com/{index}")

    response = await client.post(
        "/endpoints",
        json={"url": "https://example.com/extra", "event_types": ["*"]},
        headers=account.headers,
    )

    assert response.status_code == 409
    other = await make_tenant("other")
    await add_endpoint(other)


async def test_deleting_an_endpoint_removes_its_deliveries(
    client, make_tenant, add_endpoint, send_event, scalar
):
    account = await make_tenant("acme")
    await add_endpoint(account, url="https://example.com/kept")
    removed = await add_endpoint(account, url="https://example.com/removed")
    await send_event(account, "k1")
    assert await scalar("select count(*) from deliveries") == 2

    response = await client.delete(f"/endpoints/{removed['id']}", headers=account.headers)

    assert response.status_code == 204
    assert await scalar("select count(*) from deliveries") == 1
