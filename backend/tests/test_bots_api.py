BOT = {"handle": "eng", "name": "Engineer", "description": "Builds", "instructions": "Do it",
       "provider": "openai", "model": "gpt-5.5"}


async def test_create_list_get_update_delete(client):
    r = await client.post("/api/v1/bots", json=BOT)
    assert r.status_code == 201, r.text
    bot = r.json()
    assert bot["handle"] == "eng" and bot["tool_names"] == [] and bot["enabled"] is True and bot["instructions"] == "Do it"
    assert [b["id"] for b in (await client.get("/api/v1/bots")).json()] == [bot["id"]]
    r = await client.patch(f"/api/v1/bots/{bot['id']}", json={"name": "Eng2", "enabled": False, "instructions": "New"})
    assert r.json()["name"] == "Eng2" and r.json()["enabled"] is False and r.json()["instructions"] == "New"
    assert (await client.get(f"/api/v1/bots/{bot['id']}")).json()["name"] == "Eng2"
    actors = (await client.get("/api/v1/actors")).json()
    assert any(a["id"] == bot["id"] and a["kind"] == "bot" for a in actors)
    assert (await client.delete(f"/api/v1/bots/{bot['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/bots/{bot['id']}")).status_code == 404


async def test_validation(client):
    assert (await client.post("/api/v1/bots", json={**BOT, "handle": "Bad Handle"})).status_code == 422
    assert (await client.post("/api/v1/bots", json={**BOT, "provider": "nope"})).status_code == 422
    await client.post("/api/v1/bots", json=BOT)
    assert (await client.post("/api/v1/bots", json=BOT)).status_code == 409
    assert (await client.post("/api/v1/bots", json={**BOT, "handle": "x2", "tool_names": ["no_such_tool"]})).status_code == 422
    assert (await client.post("/api/v1/bots", json={**BOT, "handle": "x3", "tool_names": ["run_shell"],
                                                     "approval_tools": ["read_file"]})).status_code == 422


async def test_api_key_required(settings, services):
    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient

    from openbot.main import create_app
    settings.openbot_api_key = "secret"
    app = create_app(settings, services=services)
    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/api/v1/bots")).status_code == 401
        assert (await c.get("/api/v1/bots", headers={"X-API-Key": "secret"})).status_code == 200
        assert (await c.get("/api/v1/bots?api_key=secret")).status_code == 200
        assert (await c.get("/api/v1/health")).status_code == 200
