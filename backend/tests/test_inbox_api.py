BOT = {"handle": "eng", "name": "Engineer", "provider": "openai", "model": "gpt-5.5", "enabled": False}


async def test_inbox_and_ack(client):
    await client.post("/api/v1/bots", json=BOT)
    await client.post("/api/v1/actors", json={"handle": "ci", "name": "CI"})
    t = (await client.post("/api/v1/threads", json={"handles": ["eng", "ci"]})).json()
    # a message from the external actor notifies @you
    r = await client.post(f"/api/v1/threads/{t['id']}/messages", json={"content": "build failed", "from": "ci"})
    assert r.json()["message"]["sender_kind"] == "external"
    inbox = (await client.get("/api/v1/inbox")).json()
    assert len(inbox) == 1 and inbox[0]["kind"] == "message" and inbox[0]["message"]["content"] == "build failed"
    # a message from @you notifies ci
    await client.post(f"/api/v1/threads/{t['id']}/messages", json={"content": "on it"})
    ci_inbox = (await client.get("/api/v1/actors/ci/inbox")).json()
    assert [i["message"]["content"] for i in ci_inbox] == ["on it"]
    r = await client.post(f"/api/v1/inbox/{ci_inbox[0]['id']}/ack")
    assert r.json()["status"] == "done"
    assert (await client.get("/api/v1/actors/ci/inbox")).json() == []
    r = await client.post(f"/api/v1/threads/{t['id']}/ack")
    assert r.json() == {"acked": 1}
    assert (await client.get("/api/v1/inbox")).json() == []
    assert (await client.get("/api/v1/actors/ghost/inbox")).status_code == 404
