"""Image attachments: client sends {url, name} objects -> Message.meta["attachments"] -> persisted -> prompt annotation."""
PNG_URL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
GIF_URL = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"

BOT = {"handle": "eng", "name": "Engineer", "provider": "openai", "model": "gpt-5.5"}


async def _thread_with_bot(client, title):
    await client.post("/api/v1/bots", json=BOT)
    return (await client.post("/api/v1/threads", json={"title": title, "handles": ["eng"]})).json()


async def test_post_message_persists_attachments_in_meta(client, services):
    t = await _thread_with_bot(client, "imgs")
    atts = [{"url": PNG_URL, "name": "shot.png"}, {"url": GIF_URL}]
    r = await client.post(f"/api/v1/threads/{t['id']}/messages",
                          json={"content": "see attached", "attachments": atts})
    assert r.status_code == 201, r.text
    body = r.json()
    got = body["message"]["metadata"]["attachments"]
    assert [(a["url"], a.get("name")) for a in got] == [(a["url"], a.get("name")) for a in atts]

    if services.actors:
        await services.actors.wait_idle()
    d = (await client.get(f"/api/v1/threads/{t['id']}")).json()
    mine = [m for m in d["messages"] if m["content"] == "see attached"]
    assert mine
    got = mine[0]["metadata"]["attachments"]
    assert [(a["url"], a.get("name")) for a in got] == [(a["url"], a.get("name")) for a in atts]


async def test_post_message_without_attachments_has_no_attachment_meta(client):
    t = await _thread_with_bot(client, "plain")
    r = await client.post(f"/api/v1/threads/{t['id']}/messages", json={"content": "plain"})
    assert r.status_code == 201, r.text
    assert r.json()["message"]["metadata"].get("attachments", []) == []


async def test_post_message_rejects_invalid_attachment_payloads(client):
    t = await _thread_with_bot(client, "bad")
    bad_payloads = [
        [{"url": "https://example.com/a.png"}],                 # not a data URL
        [{"url": "data:image/png;base64,not-base64!!"}],        # not valid base64
        [{"url": "data:image/png;base64," + "A" * 8_000_000}],  # over the size cap
        [{"url": PNG_URL, "name": "x" * 201}],                  # name over the 200-char cap
    ]
    for atts in bad_payloads:
        r = await client.post(f"/api/v1/threads/{t['id']}/messages",
                              json={"content": "x", "attachments": atts})
        assert r.status_code == 422, f"{atts[0]['url'][:40]}: {r.text}"
