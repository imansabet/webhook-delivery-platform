import pytest

from webhook_platform.security import API_KEY_PREFIX, hash_api_key

pytestmark = pytest.mark.integration


async def test_created_tenant_authenticates_and_key_is_stored_hashed(client, make_tenant, scalar):
    account = await make_tenant("acme")

    me = await client.get("/tenants/me", headers=account.headers)

    assert me.status_code == 200
    assert me.json()["name"] == "acme"
    assert account.api_key.startswith(API_KEY_PREFIX)
    stored = await scalar("select key_hash from api_keys")
    assert stored == hash_api_key(account.api_key)
    assert stored != account.api_key


async def test_revoked_key_is_rejected(client, make_tenant, execute):
    account = await make_tenant("acme")
    await execute("update api_keys set revoked_at = now()")

    response = await client.get("/tenants/me", headers=account.headers)

    assert response.status_code == 401


async def test_tenant_key_cannot_create_tenants(client, make_tenant):
    account = await make_tenant("acme")

    response = await client.post("/tenants", json={"name": "other"}, headers=account.headers)

    assert response.status_code == 401
