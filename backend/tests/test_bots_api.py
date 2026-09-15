from sqlalchemy import select

from openbot.db.models import Actor, Run

BOT = {"handle": "eng", "name": "Engineer", "description": "Builds", "instructions": "Do it",
       "provider": "openai", "model": "gpt-5.5"}


async def test_create_list_get_update_delete(client):
    r = await client.post("/api/v1/bots", json=BOT)
    assert r.status_code == 201, r.text
    bot = r.json()
    assert bot["handle"] == "eng" and bot["tool_names"] == [] and bot["enabled"] is True and bot["instructions"] == "Do it"
    assert bot["icon"] == "robot" and bot["active"] is False
    assert [b["id"] for b in (await client.get("/api/v1/bots")).json()] == [bot["id"]]
    r = await client.patch(f"/api/v1/bots/{bot['id']}", json={"name": "Eng2", "enabled": False, "instructions": "New", "icon": "code"})
    assert r.json()["name"] == "Eng2" and r.json()["enabled"] is False and r.json()["instructions"] == "New"
    assert r.json()["icon"] == "code"
    assert (await client.get(f"/api/v1/bots/{bot['id']}")).json()["name"] == "Eng2"
    actors = (await client.get("/api/v1/actors")).json()
    assert any(a["id"] == bot["id"] and a["kind"] == "bot" for a in actors)
    assert (await client.delete(f"/api/v1/bots/{bot['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/bots/{bot['id']}")).status_code == 404


async def test_validation(client):
    assert (await client.post("/api/v1/bots", json={**BOT, "handle": "Bad Handle"})).status_code == 422
    assert (await client.post("/api/v1/bots", json={**BOT, "provider": "nope"})).status_code == 422
    assert (await client.post("/api/v1/bots", json={**BOT, "icon": "unknown"})).status_code == 422
    await client.post("/api/v1/bots", json=BOT)
    assert (await client.post("/api/v1/bots", json=BOT)).status_code == 409
    assert (await client.post("/api/v1/bots", json={**BOT, "handle": "x2", "tool_names": ["no_such_tool"]})).status_code == 422
    assert (await client.post("/api/v1/bots", json={**BOT, "handle": "x3", "tool_names": ["run_shell"],
                                                     "approval_tools": ["read_file"]})).status_code == 422


async def test_delete_refuses_while_a_run_is_open(client, services):
    bot = (await client.post("/api/v1/bots", json=BOT)).json()
    thread = (await client.post("/api/v1/threads", json={"title": "t", "handles": ["eng"]})).json()
    async with services.session_factory() as session:
        session.add(Run(actor_id=bot["id"], thread_id=thread["id"], status="running"))
        await session.commit()
    r = await client.delete(f"/api/v1/bots/{bot['id']}")
    assert r.status_code == 409 and "open runs" in r.text
    # and the bot is still there
    assert (await client.get(f"/api/v1/bots/{bot['id']}")).status_code == 200
    async with services.session_factory() as session:
        run = (await session.execute(select(Run))).scalar_one()
        run.status = "completed"
        await session.commit()
        assert (await session.execute(select(Actor).where(Actor.id == bot["id"]))).scalar_one() is not None
    assert (await client.delete(f"/api/v1/bots/{bot['id']}")).status_code == 204


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


async def test_create_with_icon_and_active_status(client, services):
    bot = (await client.post("/api/v1/bots", json={**BOT, "icon": "shield"})).json()
    assert bot["icon"] == "shield"
    thread = (await client.post("/api/v1/threads", json={"title": "t", "handles": ["eng"]})).json()
    async with services.session_factory() as session:
        session.add(Run(actor_id=bot["id"], thread_id=thread["id"], status="running"))
        await session.commit()
    listed = (await client.get("/api/v1/bots")).json()
    assert listed[0]["active"] is True
    fetched = (await client.get(f"/api/v1/bots/{bot['id']}")).json()
    assert fetched["active"] is True


async def test_waiting_human_counts_as_active(client, services):
    bot = (await client.post("/api/v1/bots", json=BOT)).json()
    thread = (await client.post("/api/v1/threads", json={"title": "t", "handles": ["eng"]})).json()
    async with services.session_factory() as session:
        session.add(Run(actor_id=bot["id"], thread_id=thread["id"], status="waiting_human"))
        await session.commit()
    assert (await client.get(f"/api/v1/bots/{bot['id']}")).json()["active"] is True
