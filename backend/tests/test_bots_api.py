import asyncio
import time

from sqlalchemy import select

from openbot.db.models import Actor, Run
from tests.fakes import call

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
    assert (await client.post("/api/v1/bots", json={**BOT, "handle": "x4", "provider": "openai", "model": ""})).status_code == 422


async def test_provider_defaults_to_auto(client):
    body = {k: v for k, v in BOT.items() if k not in ("provider", "model")}
    r = await client.post("/api/v1/bots", json={**body, "handle": "autobot"})
    assert r.status_code == 201, r.text
    bot = r.json()
    assert bot["provider"] == "auto" and bot["model"] == ""
    r = await client.patch(f"/api/v1/bots/{bot['id']}", json={"provider": "openai"})
    assert r.status_code == 422
    r = await client.patch(f"/api/v1/bots/{bot['id']}", json={"provider": "openai", "model": "gpt-5.5"})
    assert r.status_code == 200 and r.json()["provider"] == "openai" and r.json()["model"] == "gpt-5.5"
    r = await client.patch(f"/api/v1/bots/{bot['id']}", json={"provider": "auto", "model": ""})
    assert r.status_code == 200 and r.json()["provider"] == "auto"


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


async def test_idle_bot_is_not_active_for_stale_or_terminal_runs(client, services):
    """Activity is based only on canonical live run statuses, not queued history."""
    bot = (await client.post("/api/v1/bots", json={**BOT, "handle": "qa"})).json()
    thread = (await client.post("/api/v1/threads", json={"title": "qa", "handles": ["qa"]})).json()
    async with services.session_factory() as session:
        for status in ("queued", "completed", "failed", "cancelled"):
            session.add(Run(actor_id=bot["id"], thread_id=thread["id"], status=status))
        await session.commit()
    assert (await client.get(f"/api/v1/bots/{bot['id']}" )).json()["active"] is False

    async with services.session_factory() as session:
        session.add(Run(actor_id=bot["id"], thread_id=thread["id"], status="running"))
        await session.commit()
    assert (await client.get(f"/api/v1/bots/{bot['id']}" )).json()["active"] is True


async def test_waiting_human_counts_as_active(client, services):
    bot = (await client.post("/api/v1/bots", json=BOT)).json()
    thread = (await client.post("/api/v1/threads", json={"title": "t", "handles": ["eng"]})).json()
    async with services.session_factory() as session:
        session.add(Run(actor_id=bot["id"], thread_id=thread["id"], status="waiting_human"))
        await session.commit()
    assert (await client.get(f"/api/v1/bots/{bot['id']}")).json()["active"] is True


# --- bot inbox: direct posts -----------------------------------------------------------------------------

import pytest

from tests.fakes import ai


@pytest.fixture
def scripts():
    return {"eng": [ai("hi back"), ai("hi back")]}


async def test_direct_post_runs_the_bot_in_a_hidden_one_shot_thread(client, services):
    """An inbox is a queue of independent messages: each direct post gets its own one-message thread, the
    bot sees only that message plus its memories, and the exchange never shows up in the conversation views."""
    bot = (await client.post("/api/v1/bots", json=BOT)).json()
    r = await client.post(f"/api/v1/bots/{bot['id']}/inbox", json={"content": "say hi"})
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["kind"] == "message" and item["message"]["content"] == "say hi" and item["thread_id"]
    thread = (await client.get(f"/api/v1/threads/{item['thread_id']}")).json()
    assert thread["kind"] == "direct"
    assert item["thread_id"] not in [t["id"] for t in (await client.get("/api/v1/threads")).json()]   # hidden from the list
    await services.actors.wait_idle()
    rows = (await client.get(f"/api/v1/bots/{bot['id']}/inbox")).json()
    assert len(rows) == 1 and rows[0]["id"] == item["id"]
    assert rows[0]["status"] == "done" and rows[0]["run_status"] == "completed"
    assert rows[0]["reply"]["content"] == "hi back" and rows[0]["reply"]["sender_name"] == "Engineer"
    assert (await client.get("/api/v1/inbox")).json() == []                                             # no human-inbox noise
    assert (await client.post(f"/api/v1/bots/{bot['id']}/inbox", json={"content": "  "})).status_code == 422
    assert (await client.post("/api/v1/bots/nope/inbox", json={"content": "x"})).status_code == 404


async def test_bot_inbox_lists_newest_first_across_threads(client, services):
    bot = (await client.post("/api/v1/bots", json=BOT)).json()
    t = (await client.post("/api/v1/threads", json={"handles": ["eng"]})).json()
    await client.post(f"/api/v1/threads/{t['id']}/messages", json={"content": "@eng from a thread"})
    await services.actors.wait_idle()
    await client.post(f"/api/v1/bots/{bot['id']}/inbox", json={"content": "direct"})
    await services.actors.wait_idle()
    rows = (await client.get(f"/api/v1/bots/{bot['id']}/inbox")).json()
    assert [r["message"]["content"] for r in rows] == ["direct", "@eng from a thread"]
    assert {r["thread_kind"] for r in rows} == {"direct", "chat"}


# --- bot memory --------------------------------------------------------------------------------------------

async def test_list_and_delete_bot_memories(client, services):
    from openbot.runtime.memory import bot_namespace
    bot = (await client.post("/api/v1/bots", json=BOT)).json()
    ns = bot_namespace(bot["id"])
    await services.store.aput(ns, "k1", {"kind": "Memory", "content": {"content": "always wait for CI"}})
    await services.store.aput(ns, "k2", {"content": "legacy shape"})
    rows = (await client.get(f"/api/v1/bots/{bot['id']}/memories")).json()
    assert sorted((m["key"], m["content"]) for m in rows) == [("k1", "always wait for CI"), ("k2", "legacy shape")]
    assert all(m["created_at"] and m["updated_at"] for m in rows)
    assert (await client.delete(f"/api/v1/bots/{bot['id']}/memories/k1")).status_code == 204
    assert [m["key"] for m in (await client.get(f"/api/v1/bots/{bot['id']}/memories")).json()] == ["k2"]
    assert (await client.delete(f"/api/v1/bots/{bot['id']}/memories/k1")).status_code == 404
    assert (await client.get("/api/v1/bots/nope/memories")).status_code == 404


# --- purge: cancel the current run and clear the queue ------------------------------------------------------

async def test_purge_cancels_the_waiting_run_and_the_queued_mail(client, services, scripts):
    scripts["eng"] = [ai(tool_calls=[call("ask_human", question="?")]), ai("never")]
    bot = (await client.post("/api/v1/bots", json=BOT)).json()
    thread = (await client.post("/api/v1/threads", json={"title": "t", "handles": ["eng"]})).json()
    await client.post(f"/api/v1/threads/{thread['id']}/messages", json={"content": "one @eng"})
    await services.actors.wait_idle()
    await client.post(f"/api/v1/threads/{thread['id']}/messages", json={"content": "two @eng"})     # parked behind the question
    await services.actors.wait_idle()
    assert (await client.get(f"/api/v1/bots/{bot['id']}")).json()["active"] is True
    r = await client.post(f"/api/v1/bots/{bot['id']}/purge")
    assert r.status_code == 200, r.text
    assert r.json() == {"cancelled_runs": 1, "purged_items": 1}
    await services.actors.wait_idle()
    assert (await client.get(f"/api/v1/bots/{bot['id']}")).json()["active"] is False
    rows = (await client.get(f"/api/v1/bots/{bot['id']}/inbox")).json()
    # "one" was settled "done" when its run parked on the question; the run itself is now cancelled. "two" never ran.
    assert len(rows) == 2 and all(row["status"] == "cancelled" or row["run_status"] == "cancelled" for row in rows)
    assert (await client.get("/api/v1/inbox")).json() == []                  # the question left the human's inbox too
    detail = (await client.get(f"/api/v1/threads/{thread['id']}")).json()
    assert detail["runs"] == [] and detail["waiters"] == []
    log = (await client.get("/api/v1/activity", params={"actor_id": bot["id"], "event": "inbox.purged"})).json()
    assert len(log) == 1 and log[0]["detail"]["purged"] == 1 and log[0]["level"] == "warning"
    # idempotent: nothing left to purge
    assert (await client.post(f"/api/v1/bots/{bot['id']}/purge")).json() == {"cancelled_runs": 0, "purged_items": 0}
    assert (await client.post("/api/v1/bots/nope/purge")).status_code == 404


async def test_purge_cancels_a_live_run(client, services, scripts):
    def slow():
        time.sleep(1.5)          # runs in the model's executor thread, so the loop (and the purge) keep going
        yield ai("late")

    scripts["eng"] = slow()
    bot = (await client.post("/api/v1/bots", json=BOT)).json()
    thread = (await client.post("/api/v1/threads", json={"title": "t", "handles": ["eng"]})).json()
    await client.post(f"/api/v1/threads/{thread['id']}/messages", json={"content": "go @eng"})

    async def running():
        async with services.session_factory() as s:
            return (await s.execute(select(Run).where(Run.status == "running"))).scalar_one_or_none()
    for _ in range(100):
        if await running():
            break
        await asyncio.sleep(0.02)
    assert await running()
    r = await client.post(f"/api/v1/bots/{bot['id']}/purge")
    assert r.status_code == 200 and r.json()["cancelled_runs"] == 1
    await services.actors.wait_idle()
    async with services.session_factory() as s:
        run = (await s.execute(select(Run))).scalar_one()
    assert run.status == "cancelled"
    rows = (await client.get(f"/api/v1/bots/{bot['id']}/inbox")).json()
    assert [row["status"] for row in rows] == ["cancelled"]
