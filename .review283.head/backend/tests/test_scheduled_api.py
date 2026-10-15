from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from openbot.db.models import Actor


async def _thread(client):
    await client.post("/api/v1/bots", json={"handle": "eng", "name": "Engineer", "provider": "openai", "model": "x"})
    await client.post("/api/v1/bots", json={"handle": "reviewer", "name": "Reviewer", "provider": "openai", "model": "x"})
    return (await client.post("/api/v1/threads", json={"handles": ["eng", "reviewer"]})).json()


def _headers(actor="you"):
    return {"X-OpenBot-Actor": actor}


def _body(thread_id, to=None):
    return {"thread_id": thread_id, "content": "check CI", "to": to or ["eng"],
            "due_at": (datetime.now(UTC) + timedelta(minutes=2)).isoformat()}


async def test_scheduled_api_requires_explicit_actor_and_scopes(client):
    thread = await _thread(client)
    assert (await client.get("/api/v1/scheduled")).status_code == 401
    assert (await client.get("/api/v1/scheduled", headers=_headers("ghost"))).status_code == 403
    created = await client.post("/api/v1/scheduled", headers=_headers("you"), json=_body(thread["id"]))
    assert created.status_code == 201, created.text
    job = created.json()
    assert (await client.get("/api/v1/scheduled", headers=_headers("you"))).json()[0]["id"] == job["id"]
    assert (await client.get(f"/api/v1/scheduled/{job['id']}", headers=_headers("eng"))).status_code == 404
    assert (await client.post(f"/api/v1/scheduled/{job['id']}/cancel", headers=_headers("eng"))).status_code == 404
    cancelled = await client.post(f"/api/v1/scheduled/{job['id']}/cancel", headers=_headers("you"))
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"


async def test_scheduled_api_rejects_disabled_nonparticipant_and_invalid_targets(client, services):
    thread = await _thread(client)
    async with services.session_factory() as session:
        actor = (await session.execute(select(Actor).where(Actor.handle == "eng"))).scalar_one()
        actor.enabled = False
        await session.commit()
    assert (await client.get("/api/v1/scheduled", headers=_headers("eng"))).status_code == 403
    assert (await client.post("/api/v1/scheduled", headers=_headers("you"), json=_body("missing"))).status_code == 404
    invalid = _body(thread["id"], ["ghost"])
    assert (await client.post("/api/v1/scheduled", headers=_headers("you"), json=invalid)).status_code == 422


async def test_scheduled_api_rejects_actor_outside_thread(client):
    thread = await _thread(client)
    await client.post("/api/v1/bots", json={"handle": "other", "name": "Other", "provider": "openai", "model": "x"})
    # The other bot is enabled but is not a participant in this thread.
    assert (await client.post("/api/v1/scheduled", headers=_headers("other"), json=_body(thread["id"]))).status_code == 403
