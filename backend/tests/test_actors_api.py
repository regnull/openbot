async def test_external_actor_crud(client):
    r = await client.post("/api/v1/actors", json={"handle": "ci", "name": "CI", "webhook_url": "http://ci/hook",
                                                  "webhook_secret": "s"})
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["kind"] == "external" and a["webhook_url"] == "http://ci/hook" and "webhook_secret" not in a
    r = await client.patch(f"/api/v1/actors/{a['id']}", json={"name": "CI2", "webhook_url": None})
    assert r.json()["name"] == "CI2" and r.json()["webhook_url"] is None
    handles = {x["handle"] for x in (await client.get("/api/v1/actors")).json()}
    assert {"you", "ci"} <= handles
    you = next(x for x in (await client.get("/api/v1/actors")).json() if x["handle"] == "you")
    assert (await client.delete(f"/api/v1/actors/{you['id']}")).status_code == 409
    assert (await client.delete(f"/api/v1/actors/{a['id']}")).status_code == 204
    assert (await client.post("/api/v1/actors", json={"handle": "you", "name": "dup"})).status_code == 409


BOT = {"handle": "eng", "name": "Engineer", "provider": "openai", "model": "gpt-5.5", "enabled": False}


async def test_actor_message_shortcut(client):
    await client.post("/api/v1/bots", json=BOT)
    await client.post("/api/v1/actors", json={"handle": "ci", "name": "CI"})
    r = await client.post("/api/v1/actors/eng/messages", json={"content": "ping", "from": "ci", "external_ref": "pr-12"})
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["thread"]["external_ref"] == "pr-12" and b["message"]["sender_kind"] == "external" and b["addressed"] == []
    assert sorted(p["handle"] for p in b["thread"]["participants"]) == ["ci", "eng", "you"]
    r2 = await client.post("/api/v1/actors/eng/messages", json={"content": "again", "from": "ci", "external_ref": "pr-12"})
    assert r2.json()["thread"]["id"] == b["thread"]["id"]
    r3 = await client.post("/api/v1/actors/eng/messages", json={"content": "fresh"})
    assert r3.json()["thread"]["id"] != b["thread"]["id"] and r3.json()["message"]["sender_kind"] == "human"
    r4 = await client.post("/api/v1/actors/ci/messages", json={"content": "to ci", "thread_id": b["thread"]["id"]})
    assert r4.json()["thread"]["id"] == b["thread"]["id"]
    assert (await client.post("/api/v1/actors/ghost/messages", json={"content": "x"})).status_code == 404
