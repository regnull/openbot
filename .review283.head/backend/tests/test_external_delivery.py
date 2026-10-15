import hashlib
import hmac
import json

import httpx
from sqlalchemy import select

from openbot.db.models import InboxItem
from openbot.runtime.actors import sign
from tests.fakes import ai

BOT = {"handle": "eng", "name": "Engineer", "provider": "openai", "model": "gpt-5.5"}


def test_sign():
    assert sign("s", b"body") == "sha256=" + hmac.new(b"s", b"body", hashlib.sha256).hexdigest()


async def test_delivery_with_retry_and_question(client, services, scripts):
    from tests.fakes import call
    scripts["eng"] = [ai(tool_calls=[call("ask_human", question="Deploy?")]), ai("deployed")]
    received, calls = [], {"n": 0}

    def handler(request: httpx.Request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500)
        received.append(request)
        return httpx.Response(204)

    services.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await client.post("/api/v1/bots", json=BOT)
    await client.post("/api/v1/actors", json={"handle": "ci", "name": "CI", "webhook_url": "http://ci/hook", "webhook_secret": "s"})
    t = (await client.post("/api/v1/threads", json={"handles": ["eng", "ci"]})).json()
    await client.post(f"/api/v1/threads/{t['id']}/messages", json={"content": "@eng go"})
    await services.actors.wait_idle()
    for _ in range(50):
        if len(received) >= 2:
            break
        import asyncio
        await asyncio.sleep(0.02)
    kinds = [r.headers["X-OpenBot-Kind"] for r in received]
    assert kinds == ["message", "question"]
    first = received[0]
    assert first.headers["X-OpenBot-Signature"] == sign("s", first.content)
    body = json.loads(first.content)
    assert body["message"]["content"] == "@eng go" and body["thread_id"] == t["id"]
    q = json.loads(received[1].content)
    assert q["question"]["interrupt"]["question"] == "Deploy?" and q["question"]["run_id"]
    async with services.session_factory() as s:
        items = (await s.execute(select(InboxItem))).scalars().all()
        ci_items = [i for i in items if i.kind in ("message", "question") and i.status == "done" and i.attempts >= 1]
    assert len(ci_items) >= 2 and max(i.attempts for i in ci_items) == 2
