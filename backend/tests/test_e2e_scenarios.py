"""End-to-end scenarios driven entirely through the public HTTP API, with a scripted model standing
in for the LLM. Each test is a full slice of the actor/bot/thread system rather than one unit, and
they get progressively more complex: a single bot answering, a bot calling a tool, a hand-off between
two bots, a multi-turn thread running to a quiescent end, and two threads processed concurrently.
"""
import asyncio

from sqlalchemy import update

from openbot.db.models import Thread
from tests.fakes import ScriptedChatModel, ai, call

BOT = {"handle": "eng", "name": "Engineer", "provider": "openai", "model": "m"}
REVIEWER = {"handle": "rev", "name": "Reviewer", "provider": "openai", "model": "m"}


async def runs_for(client, thread_id):
    r = await client.get("/api/v1/runs", params={"thread_id": thread_id})
    assert r.status_code == 200, r.text
    return r.json()


async def thread_detail(client, thread_id):
    r = await client.get(f"/api/v1/threads/{thread_id}")
    assert r.status_code == 200, r.text
    return r.json()


async def suppress_auto_rename(services, thread_id):
    """The platform auto-renames a thread from its default bot's model once it reaches 3 messages
    (openbot.runtime.renaming), which would silently steal one entry from that bot's scripted replies.
    Irrelevant to the scenarios below, so it is switched off up front."""
    async with services.session_factory() as s:
        await s.execute(update(Thread).where(Thread.id == thread_id).values(auto_renamed=True))
        await s.commit()


# 1. Simple: one bot answers a message ------------------------------------------------------------

async def test_simple_reply(client, services, scripts):
    scripts["eng"] = [ai("Hello! How can I help?")]
    await client.post("/api/v1/bots", json=BOT)
    t = (await client.post("/api/v1/threads", json={"handles": ["eng"]})).json()

    r = await client.post(f"/api/v1/threads/{t['id']}/messages", json={"content": "hi"})
    assert r.status_code == 201, r.text
    assert r.json()["addressed"] == ["eng"]
    await services.actors.wait_idle()

    d = await thread_detail(client, t["id"])
    assert d["active"] is False
    assert [m["sender_name"] for m in d["messages"]] == ["You", "Engineer"]
    assert d["messages"][-1]["content"] == "Hello! How can I help?"
    assert [r["status"] for r in await runs_for(client, t["id"])] == ["completed"]


# 2. A bot calls a tool before replying ------------------------------------------------------------

async def test_bot_calls_a_tool_then_replies(client, services, scripts):
    scripts["eng"] = [ai(tool_calls=[call("list_bots")]), ai("Only rev is around; no need to loop anyone in yet.")]
    await client.post("/api/v1/bots", json=BOT)
    await client.post("/api/v1/bots", json=REVIEWER)
    t = (await client.post("/api/v1/threads", json={"handles": ["eng"]})).json()

    await client.post(f"/api/v1/threads/{t['id']}/messages", json={"content": "who else is on the platform?"})
    await services.actors.wait_idle()

    rs = await runs_for(client, t["id"])
    assert [r["status"] for r in rs] == ["completed"]
    detail = (await client.get(f"/api/v1/runs/{rs[0]['id']}")).json()
    event_types = [e["type"] for e in detail["events"]]
    assert "tool_call" in event_types and "tool_result" in event_types
    tool_call = next(e for e in detail["events"] if e["type"] == "tool_call")
    tool_result = next(e for e in detail["events"] if e["type"] == "tool_result")
    assert tool_call["payload"]["name"] == "list_bots"
    assert "@rev" in tool_result["payload"]["content"]     # the tool actually queried the DB for other bots

    d = await thread_detail(client, t["id"])
    assert d["messages"][-1]["content"] == "Only rev is around; no need to loop anyone in yet."
    assert d["active"] is False and d["waiters"] == []      # no handoff triggered, thread fully drained


# 3. Hand-off from one bot to another ---------------------------------------------------------------

async def test_bot_to_bot_handoff(client, services, scripts):
    scripts["eng"] = [ai("Built it. @rev please review.")]
    scripts["rev"] = [ai("Reviewed, looks good.")]
    await client.post("/api/v1/bots", json=BOT)
    await client.post("/api/v1/bots", json=REVIEWER)
    t = (await client.post("/api/v1/threads", json={"handles": ["eng", "rev"]})).json()

    r = await client.post(f"/api/v1/threads/{t['id']}/messages", json={"content": "@eng build the feature"})
    assert r.json()["addressed"] == ["eng"]
    await services.actors.wait_idle()

    d = await thread_detail(client, t["id"])
    assert [(m["sender_name"], m["content"]) for m in d["messages"]] == [
        ("You", "@eng build the feature"),
        ("Engineer", "Built it. @rev please review."),
        ("Reviewer", "Reviewed, looks good."),
    ]
    rs = await runs_for(client, t["id"])
    assert len(rs) == 2 and all(x["status"] == "completed" for x in rs)
    assert d["active"] is False and d["waiters"] == []


# 4. Full thread lifecycle: start, multiple hops, back to the human, quiescent end -------------------

async def test_thread_runs_to_completion_across_multiple_turns(client, services, scripts):
    # eng is both a worker and this thread's default bot (its usual coordinator role): a plain reply
    # with no @mention from another bot falls back to the default bot (router.resolve_targets), so
    # rev's unaddressed "LGTM" naturally reports back to eng, while eng's own unaddressed replies are
    # self-excluded from that same fallback and simply end the exchange.
    scripts["eng"] = [ai("Building... @rev please review."), ai("Thanks, closing this out."), ai("Anytime!")]
    scripts["rev"] = [ai("LGTM, merged.")]
    await client.post("/api/v1/bots", json=BOT)
    await client.post("/api/v1/bots", json=REVIEWER)
    t = (await client.post("/api/v1/threads",
                           json={"handles": ["eng", "rev"], "default_bot_handle": "eng"})).json()
    assert t["default_bot_handle"] == "eng"
    await suppress_auto_rename(services, t["id"])

    r1 = await client.post(f"/api/v1/threads/{t['id']}/messages", json={"content": "build the feature"})
    assert r1.json()["addressed"] == ["eng"]          # routed to the default bot, no explicit @mention
    await services.actors.wait_idle()

    mid = await thread_detail(client, t["id"])
    assert [(m["sender_name"], m["content"]) for m in mid["messages"]] == [
        ("You", "build the feature"),
        ("Engineer", "Building... @rev please review."),
        ("Reviewer", "LGTM, merged."),
        ("Engineer", "Thanks, closing this out."),      # rev's unaddressed reply reported back to the default bot
    ]
    assert mid["active"] is False and mid["waiters"] == []

    r2 = await client.post(f"/api/v1/threads/{t['id']}/messages", json={"content": "thanks team!"})
    assert r2.json()["addressed"] == ["eng"]
    await services.actors.wait_idle()

    d = await thread_detail(client, t["id"])
    assert [(m["sender_name"], m["content"]) for m in d["messages"]] == [
        ("You", "build the feature"),
        ("Engineer", "Building... @rev please review."),
        ("Reviewer", "LGTM, merged."),
        ("Engineer", "Thanks, closing this out."),
        ("You", "thanks team!"),
        ("Engineer", "Anytime!"),
    ]
    rs = await runs_for(client, t["id"])
    assert len(rs) == 4 and all(x["status"] == "completed" for x in rs)
    # Fully drained: not active and nobody left waiting to pick up mail.
    assert d["active"] is False and d["waiters"] == []


# 5. Two threads processed concurrently -------------------------------------------------------------

class Slow:
    """A scripted reply with a delay before the first one, wide enough for both threads' runs to be
    "running" at once when polled -- the delay happens in the model's executor thread, so the event
    loop (and the other thread's worker) keeps making progress."""

    def __init__(self, replies, delay=0.3):
        self.replies, self.delay, self.first = iter(replies), delay, True

    def __iter__(self):
        return self

    def __next__(self):
        if self.first:
            self.first = False
            import time
            time.sleep(self.delay)
        return next(self.replies)


async def test_two_threads_process_concurrently(client, services):
    await client.post("/api/v1/bots", json=BOT)
    await client.post("/api/v1/bots", json=REVIEWER)
    base_factory = services.model_factory
    slow = {"eng": Slow([ai("Thread A handled by eng.")]), "rev": Slow([ai("Thread B handled by rev.")])}
    services.model_factory = lambda actor: ScriptedChatModel(messages=slow[actor.handle]) if actor.handle in slow else base_factory(actor)

    tA = (await client.post("/api/v1/threads", json={"handles": ["eng"]})).json()
    tB = (await client.post("/api/v1/threads", json={"handles": ["rev"]})).json()

    postA, postB = await asyncio.gather(
        client.post(f"/api/v1/threads/{tA['id']}/messages", json={"content": "@eng go"}),
        client.post(f"/api/v1/threads/{tB['id']}/messages", json={"content": "@rev go"}),
    )
    assert postA.status_code == 201 and postB.status_code == 201

    async def both_running():
        ra, rb = await asyncio.gather(runs_for(client, tA["id"]), runs_for(client, tB["id"]))
        return any(r["status"] == "running" for r in ra) and any(r["status"] == "running" for r in rb)

    loop = asyncio.get_running_loop()
    deadline = loop.time() + 3.0
    overlapped = False
    while loop.time() < deadline:
        if await both_running():
            overlapped = True
            break
        await asyncio.sleep(0.02)
    assert overlapped, "the two threads never ran at the same time"

    await services.actors.wait_idle(timeout=10)

    dA, dB = await thread_detail(client, tA["id"]), await thread_detail(client, tB["id"])
    assert [m["content"] for m in dA["messages"]] == ["@eng go", "Thread A handled by eng."]
    assert [m["content"] for m in dB["messages"]] == ["@rev go", "Thread B handled by rev."]
    assert dA["active"] is False and dB["active"] is False
    assert [r["status"] for r in await runs_for(client, tA["id"])] == ["completed"]
    assert [r["status"] for r in await runs_for(client, tB["id"])] == ["completed"]
