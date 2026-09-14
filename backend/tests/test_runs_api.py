import pytest

from tests.fakes import ai, call

BOT = {"handle": "eng", "name": "Engineer", "provider": "openai", "model": "gpt-5.5"}


@pytest.fixture
def scripts():
    return {"eng": [ai(tool_calls=[call("ask_human", question="Merge?")]), ai("Merged.")]}


async def test_run_lifecycle_via_api(client, services):
    await client.post("/api/v1/bots", json=BOT)
    t = (await client.post("/api/v1/threads", json={"handles": ["eng"]})).json()
    await client.post(f"/api/v1/threads/{t['id']}/messages", json={"content": "go"})
    await services.actors.wait_idle()
    run = (await client.get(f"/api/v1/runs?thread_id={t['id']}")).json()[0]
    assert run["status"] == "waiting_human" and run["interrupt"]["question"] == "Merge?"
    d = (await client.get(f"/api/v1/runs/{run['id']}")).json()
    assert [e["type"] for e in d["events"]] == ["tool_call", "interrupt"]
    inbox = (await client.get("/api/v1/inbox")).json()
    assert [i["kind"] for i in inbox] == ["question"]
    assert (await client.post(f"/api/v1/runs/{run['id']}/resume", json={"decisions": ["approve"]})).status_code == 422
    r = await client.post(f"/api/v1/runs/{run['id']}/resume", json={"answer": "yes"})
    assert r.status_code == 200
    await services.actors.wait_idle()
    assert (await client.get(f"/api/v1/runs/{run['id']}")).json()["status"] == "completed"
    assert [i["kind"] for i in (await client.get("/api/v1/inbox")).json()] == ["message"]   # question acked, reply unread
    assert (await client.post(f"/api/v1/runs/{run['id']}/resume", json={"answer": "x"})).status_code == 409
    assert (await client.post(f"/api/v1/runs/{run['id']}/cancel")).status_code == 409
