BOT = {"handle": "eng", "name": "Engineer", "provider": "openai", "model": "gpt-5.5"}


async def test_thread_flow(client, services):
    await client.post("/api/v1/bots", json=BOT)
    r = await client.post("/api/v1/threads", json={"title": "Work", "handles": ["eng"]})
    assert r.status_code == 201, r.text
    t = r.json()
    assert sorted(p["handle"] for p in t["participants"]) == ["eng", "you"]
    r = await client.post(f"/api/v1/threads/{t['id']}/messages", json={"content": "hello"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["message"]["sender_kind"] == "human" and body["message"]["sender_name"] == "You"
    assert body["addressed"] == ["eng"] and body["unaddressed"] is False
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


async def test_pagination(client, services):
    await client.post("/api/v1/bots", json={**BOT, "enabled": False})
    t = (await client.post("/api/v1/threads", json={"handles": ["eng"]})).json()
    for i in range(5):
        await client.post(f"/api/v1/threads/{t['id']}/messages", json={"content": f"m{i}"})
    d = (await client.get(f"/api/v1/threads/{t['id']}?limit=2")).json()
    assert [m["content"] for m in d["messages"]] == ["m3", "m4"] and d["has_more"] is True
    d2 = (await client.get(f"/api/v1/threads/{t['id']}?limit=2&before={d['messages'][0]['id']}")).json()
    assert [m["content"] for m in d2["messages"]] == ["m1", "m2"]
