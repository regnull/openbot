"""Image attachments: client sends data URLs -> Message.meta["images"] -> persisted -> prompt annotation."""
PNG_URL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
GIF_URL = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"

BOT = {"handle": "eng", "name": "Engineer", "provider": "openai", "model": "gpt-5.5"}


async def _thread_with_bot(client, title):
    await client.post("/api/v1/bots", json=BOT)
    return (await client.post("/api/v1/threads", json={"title": title, "handles": ["eng"]})).json()


async def test_post_message_persists_images_in_meta(client, services):
    t = await _thread_with_bot(client, "imgs")
    r = await client.post(f"/api/v1/threads/{t['id']}/messages",
                          json={"content": "see attached", "images": [PNG_URL, GIF_URL]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["message"]["metadata"]["images"] == [PNG_URL, GIF_URL]

    if services.actors:
        await services.actors.wait_idle()
    d = (await client.get(f"/api/v1/threads/{t['id']}")).json()
    mine = [m for m in d["messages"] if m["content"] == "see attached"]
    assert mine and mine[0]["metadata"]["images"] == [PNG_URL, GIF_URL]


async def test_post_message_without_images_has_no_images_meta(client):
    t = await _thread_with_bot(client, "plain")
    r = await client.post(f"/api/v1/threads/{t['id']}/messages", json={"content": "plain"})
    assert r.status_code == 201, r.text
    assert r.json()["message"]["metadata"].get("images", []) == []


async def test_post_message_rejects_invalid_image_payloads(client):
    t = await _thread_with_bot(client, "bad")
    bad_payloads = [
        ["https://example.com/a.png"],              # not a data URL
        ["data:image/png;base64,not-base64!!"],     # not valid base64
        ["data:image/png;base64," + "A" * 8_000_000],  # over the size cap
    ]
    for images in bad_payloads:
        r = await client.post(f"/api/v1/threads/{t['id']}/messages",
                              json={"content": "x", "images": images})
        assert r.status_code == 422, f"{images[0][:40]}: {r.text}"
