import re
from datetime import datetime, timedelta

from sqlalchemy import select

from openbot.db.models import Actor, Run

from openbot.runtime.delivery import TITLE_TIME_FORMAT


def _expected_recent_titles() -> set[str]:
    """The current local time (+-1 minute), formatted the way the backend should."""
    now = datetime.now().astimezone()
    return {
        (now + offset).strftime(TITLE_TIME_FORMAT)
        for offset in (timedelta(minutes=-1), timedelta(), timedelta(minutes=1))
    }


BOT = {"handle": "eng", "name": "Engineer", "provider": "openai", "model": "gpt-5.5"}
CHIEF = {"handle": "chief_of_staff", "name": "Chief of Staff", "provider": "openai", "model": "gpt-5.5"}
REVIEWER = {"handle": "reviewer", "name": "Reviewer", "provider": "openai", "model": "gpt-5.5"}


async def test_thread_flow(client, services):
    await client.post("/api/v1/bots", json=CHIEF)
    await client.post("/api/v1/bots", json=BOT)
    r = await client.post("/api/v1/threads", json={"title": "Work", "handles": ["eng"]})
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["working_directory"] is None
    assert sorted(p["handle"] for p in t["participants"]) == ["chief_of_staff", "eng", "you"]
    assert t["default_bot_handle"] == "chief_of_staff"
    r = await client.post(f"/api/v1/threads/{t['id']}/messages", json={"content": "hello"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["message"]["sender_kind"] == "human" and body["message"]["sender_name"] == "You"
    assert body["addressed"] == ["chief_of_staff"] and body["unaddressed"] is False
    if services.actors:
        await services.actors.wait_idle()
    d = (await client.get(f"/api/v1/threads/{t['id']}")).json()
    assert d["messages"][0]["content"] == "hello" and d["has_more"] is False
    assert (await client.get("/api/v1/threads")).json()[0]["id"] == t["id"]
    assert (await client.post(f"/api/v1/threads/{t['id']}/messages", json={"content": "x", "to": ["ghost"]})).status_code == 422
    assert (await client.post(f"/api/v1/threads/{t['id']}/messages", json={"content": "x", "from": "ghost"})).status_code == 422
    assert (await client.post("/api/v1/threads", json={"handles": ["ghost"]})).status_code == 422
    assert (await client.delete(f"/api/v1/threads/{t['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/threads/{t['id']}")).status_code == 404


async def test_thread_detail_active_matches_live_runs(client, services):
    await client.post("/api/v1/bots", json=BOT)
    t = (await client.post("/api/v1/threads", json={"handles": ["eng"]})).json()
    async with services.session_factory() as session:
        actor = (await session.execute(select(Actor).where(Actor.handle == "eng"))).scalar_one()
        session.add(Run(actor_id=actor.id, thread_id=t["id"], status="running"))
        await session.commit()
    detail = await client.get(f"/api/v1/threads/{t['id']}")
    assert detail.status_code == 200
    assert detail.json()["active"] is True


async def test_create_thread_with_custom_working_directory(client, services):
    services.settings.workspace_root.mkdir(parents=True)
    (services.settings.workspace_root / "project" / "src").mkdir(parents=True)
    await client.post("/api/v1/bots", json=CHIEF)

    r = await client.post("/api/v1/threads", json={"title": "Project", "working_directory": "project/../project/src"})
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["working_directory"] == "project/src"

    d = (await client.get(f"/api/v1/threads/{t['id']}")).json()
    assert d["working_directory"] == "project/src"
    listed = (await client.get("/api/v1/threads")).json()[0]
    assert listed["working_directory"] == "project/src"


async def test_create_thread_rejects_invalid_working_directory(client, services):
    services.settings.workspace_root.mkdir(parents=True)
    (services.settings.workspace_root / "file.txt").write_text("not a dir")
    await client.post("/api/v1/bots", json=CHIEF)

    cases = ["../escape", "missing", "file.txt", "bad\npath"]
    for directory in cases:
        r = await client.post("/api/v1/threads", json={"working_directory": directory})
        assert r.status_code == 422, (directory, r.text)
        assert "working_directory" in r.text


async def test_change_thread_default_and_explicit_mention_precedence(client, services):
    await client.post("/api/v1/bots", json=CHIEF)
    await client.post("/api/v1/bots", json=BOT)
    await client.post("/api/v1/bots", json=REVIEWER)
    t = (await client.post("/api/v1/threads", json={"handles": ["eng"]})).json()
    assert t["default_bot_handle"] == "chief_of_staff"
    assert sorted(p["handle"] for p in t["participants"]) == ["chief_of_staff", "eng", "you"]

    r = await client.patch(f"/api/v1/threads/{t['id']}", json={"default_bot_handle": "reviewer"})
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["default_bot_handle"] == "reviewer"
    assert sorted(p["handle"] for p in updated["participants"]) == ["chief_of_staff", "eng", "reviewer", "you"]

    r = await client.post(f"/api/v1/threads/{t['id']}/messages", json={"content": "hello"})
    assert r.status_code == 201, r.text
    assert r.json()["addressed"] == ["reviewer"]
    r = await client.post(f"/api/v1/threads/{t['id']}/messages", json={"content": "@eng please"})
    assert r.status_code == 201, r.text
    assert r.json()["addressed"] == ["eng"]
    assert (await client.patch(f"/api/v1/threads/{t['id']}", json={"default_bot_handle": "ghost"})).status_code == 422


async def test_deleted_default_bot_falls_back_to_chief(client, services):
    await client.post("/api/v1/bots", json=CHIEF)
    await client.post("/api/v1/bots", json=BOT)
    reviewer = (await client.post("/api/v1/bots", json=REVIEWER)).json()
    t = (await client.post("/api/v1/threads", json={"handles": ["eng"], "default_bot_handle": "reviewer"})).json()
    assert t["default_bot_handle"] == "reviewer"

    r = await client.delete(f"/api/v1/bots/{reviewer['id']}")
    assert r.status_code == 204, r.text

    d = (await client.get(f"/api/v1/threads/{t['id']}")).json()
    assert d["default_bot_actor_id"] is None
    assert d["default_bot_handle"] == "chief_of_staff"
    r = await client.post(f"/api/v1/threads/{t['id']}/messages", json={"content": "hello"})
    assert r.status_code == 201, r.text
    assert r.json()["addressed"] == ["chief_of_staff"]


async def test_pagination(client, services):
    await client.post("/api/v1/bots", json={**BOT, "enabled": False})
    t = (await client.post("/api/v1/threads", json={"handles": ["eng"]})).json()
    for i in range(5):
        await client.post(f"/api/v1/threads/{t['id']}/messages", json={"content": f"m{i}"})
    d = (await client.get(f"/api/v1/threads/{t['id']}?limit=2")).json()
    assert [m["content"] for m in d["messages"]] == ["m3", "m4"] and d["has_more"] is True
    d2 = (await client.get(f"/api/v1/threads/{t['id']}?limit=2&before={d['messages'][0]['id']}")).json()
    assert [m["content"] for m in d2["messages"]] == ["m1", "m2"]



async def test_create_thread_blank_title_is_timestamp_even_with_handles(client, services):
    """Blank title is timestamped even when handles are provided (user asked for timestamp titles)."""
    await client.post("/api/v1/bots", json={**CHIEF})
    await client.post("/api/v1/bots", json={**BOT})
    r = await client.post("/api/v1/threads", json={"title": "", "handles": ["eng", "chief_of_staff"]})
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["title"] in _expected_recent_titles(), t["title"]


async def test_create_thread_blank_title_is_timestamp_even_with_default_bot(client, services):
    """Blank title is timestamped even when default_bot_handle is set."""
    await client.post("/api/v1/bots", json={**CHIEF})
    r = await client.post("/api/v1/threads", json={"title": "", "handles": [], "default_bot_handle": "chief_of_staff"})
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["title"] in _expected_recent_titles(), t["title"]


async def test_create_thread_auto_title_datetime(client, services):
    """When title is empty, fall back to 'YYYY-MM-DD HH:MM' local time."""
    r = await client.post("/api/v1/threads", json={"title": "", "handles": []})
    assert r.status_code == 201, r.text
    t = r.json()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", t["title"]), t["title"]
    assert t["title"] in _expected_recent_titles(), t["title"]


async def test_create_thread_explicit_title_preserved(client, services):
    """Explicit title should not be overridden by auto-generation."""
    await client.post("/api/v1/bots", json={**CHIEF})
    await client.post("/api/v1/bots", json={**BOT})
    r = await client.post("/api/v1/threads", json={"title": "My Custom Title", "handles": ["eng"]})
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["title"] == "My Custom Title"


async def test_create_thread_auto_title_whitespace(client, services):
    """Whitespace-only title should be treated as not provided and become the timestamp."""
    await client.post("/api/v1/bots", json={**CHIEF})
    r = await client.post("/api/v1/threads", json={"title": "   ", "handles": []})
    assert r.status_code == 201, r.text
    t = r.json()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", t["title"]), t["title"]
    assert t["title"] in _expected_recent_titles(), t["title"]


async def test_create_thread_explicit_title_whitespace_preserved(client, services):
    """Titles with meaningful content keep surrounding whitespace verbatim (no stripping)."""
    r = await client.post("/api/v1/threads", json={"title": "  Padded Title  ", "handles": []})
    assert r.status_code == 201, r.text
    assert r.json()["title"] == "  Padded Title  "
