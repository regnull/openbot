BOT = {"handle": "eng", "name": "Engineer", "provider": "openai", "model": "gpt-5.5"}
CHIEF = {"handle": "chief_of_staff", "name": "Chief of Staff", "provider": "openai", "model": "gpt-5.5"}
REVIEWER = {"handle": "reviewer", "name": "Reviewer", "provider": "openai", "model": "gpt-5.5"}


async def test_thread_flow(client, services):
    await client.post("/api/v1/bots", json=CHIEF)
    await client.post("/api/v1/bots", json=BOT)
    r = await client.post("/api/v1/threads", json={"title": "Work", "handles": ["eng"]})
    assert r.status_code == 201, r.text
    t = r.json()
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
