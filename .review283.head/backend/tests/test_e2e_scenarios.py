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
QA = {"handle": "qa", "name": "QA", "provider": "openai", "model": "m"}


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


async def poll_until(check, timeout=3.0, interval=0.02):
    """Poll an async `check()` until it returns something truthy; raises if it never does."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if (result := await check()):
            return result
        await asyncio.sleep(interval)
    raise AssertionError("condition not met within timeout")


def statuses(runs):
    return [r["status"] for r in runs]


# 6. The same bot serializes its own backlog across two threads, without blocking a third thread on a
#    different bot ---------------------------------------------------------------------------------

async def test_same_bot_across_two_threads_does_not_block_a_third_bots_thread(client, services):
    """eng has one worker: mail queued for it in two different threads is handled one thread at a
    time, never two eng runs at once. That backlog must not stall rev, which has its own worker and
    its own thread, and should complete independently while eng is still working through its own."""
    await client.post("/api/v1/bots", json=BOT)
    await client.post("/api/v1/bots", json=REVIEWER)
    base_factory = services.model_factory
    slow = {"eng": Slow([ai("Handled."), ai("Handled.")], delay=0.4), "rev": Slow([ai("Reviewed.")], delay=0.2)}
    services.model_factory = lambda actor: ScriptedChatModel(messages=slow[actor.handle]) if actor.handle in slow else base_factory(actor)

    tA = (await client.post("/api/v1/threads", json={"handles": ["eng"]})).json()
    tB = (await client.post("/api/v1/threads", json={"handles": ["eng"]})).json()
    tC = (await client.post("/api/v1/threads", json={"handles": ["rev"]})).json()

    await asyncio.gather(
        client.post(f"/api/v1/threads/{tA['id']}/messages", json={"content": "@eng go"}),
        client.post(f"/api/v1/threads/{tB['id']}/messages", json={"content": "@eng go"}),
        client.post(f"/api/v1/threads/{tC['id']}/messages", json={"content": "@rev go"}),
    )

    async def eng_and_rev_running_together():
        ra, rb, rc = await asyncio.gather(*(runs_for(client, t["id"]) for t in (tA, tB, tC)))
        eng_running = sum("running" in statuses(rs) for rs in (ra, rb))
        return eng_running == 1 and "running" in statuses(rc)

    await poll_until(eng_and_rev_running_together)      # rev's thread progressed while eng was still busy
    await services.actors.wait_idle(timeout=10)

    dA, dB, dC = await thread_detail(client, tA["id"]), await thread_detail(client, tB["id"]), await thread_detail(client, tC["id"])
    assert [m["content"] for m in dA["messages"]] == ["@eng go", "Handled."]
    assert [m["content"] for m in dB["messages"]] == ["@eng go", "Handled."]
    assert [m["content"] for m in dC["messages"]] == ["@rev go", "Reviewed."]
    assert not any(d["active"] for d in (dA, dB, dC))
    # eng never ran the two threads at once: two separate completed runs, one per thread.
    eng_runs = await asyncio.gather(runs_for(client, tA["id"]), runs_for(client, tB["id"]))
    assert all(statuses(rs) == ["completed"] for rs in eng_runs)
    assert statuses(await runs_for(client, tC["id"])) == ["completed"]


# 7. The concurrency cap is enforced across threads, not just within one ----------------------------

async def test_concurrency_cap_is_enforced_across_three_threads(client, services):
    """max_concurrent_runs caps how many runs are live platform-wide at once, regardless of which
    thread or bot they belong to: with the cap set to 2, three threads on three different bots produce
    at most two simultaneous "running" runs, and the third has no run row at all until a slot frees up
    (a queued bot creates its run only once it actually gets to work -- see run.created bookkeeping)."""
    from openbot.runtime.actors import ActorSystem

    await client.post("/api/v1/bots", json=BOT)
    await client.post("/api/v1/bots", json=REVIEWER)
    await client.post("/api/v1/bots", json=QA)
    await services.actors.stop()
    services.settings.max_concurrent_runs = 2
    services.actors = ActorSystem(services, 2)
    await services.actors.start()

    base_factory = services.model_factory
    slow = {"eng": Slow([ai("eng done.")], delay=0.4), "rev": Slow([ai("rev done.")], delay=0.4),
           "qa": Slow([ai("qa done.")], delay=0.4)}
    services.model_factory = lambda actor: ScriptedChatModel(messages=slow[actor.handle]) if actor.handle in slow else base_factory(actor)

    threads = {h: (await client.post("/api/v1/threads", json={"handles": [h]})).json() for h in ("eng", "rev", "qa")}
    await asyncio.gather(*(client.post(f"/api/v1/threads/{t['id']}/messages", json={"content": f"@{h} go"})
                          for h, t in threads.items()))

    async def exactly_two_running_one_still_queued():
        by_handle = {h: await runs_for(client, t["id"]) for h, t in threads.items()}
        running = [h for h, rs in by_handle.items() if "running" in statuses(rs)]
        waiting = [h for h, rs in by_handle.items() if rs == []]      # no run row yet: still queued for a slot
        return len(running) == 2 and len(waiting) == 1

    await poll_until(exactly_two_running_one_still_queued)
    await services.actors.wait_idle(timeout=10)

    for h, t in threads.items():
        d = await thread_detail(client, t["id"])
        assert [m["content"] for m in d["messages"]] == [f"@{h} go", f"{h} done."]
        assert d["active"] is False
        assert statuses(await runs_for(client, t["id"])) == ["completed"]


# 8. Cancelling one thread's run does not disturb a run concurrently in flight in another thread -----

async def test_cancelling_one_threads_run_leaves_a_concurrent_thread_unaffected(client, services):
    await client.post("/api/v1/bots", json=BOT)
    await client.post("/api/v1/bots", json=REVIEWER)
    base_factory = services.model_factory
    slow = {"eng": Slow([ai("finished (should never be seen)")], delay=1.0),
           "rev": Slow([ai("Reviewed, all good.")], delay=0.2)}
    services.model_factory = lambda actor: ScriptedChatModel(messages=slow[actor.handle]) if actor.handle in slow else base_factory(actor)

    tA = (await client.post("/api/v1/threads", json={"handles": ["eng"]})).json()
    tB = (await client.post("/api/v1/threads", json={"handles": ["rev"]})).json()
    await asyncio.gather(
        client.post(f"/api/v1/threads/{tA['id']}/messages", json={"content": "@eng go"}),
        client.post(f"/api/v1/threads/{tB['id']}/messages", json={"content": "@rev go"}),
    )

    async def eng_running():
        rs = await runs_for(client, tA["id"])
        return next((r for r in rs if r["status"] == "running"), None)

    run = await poll_until(eng_running)
    # A live run is cancelled cooperatively (the worker's task is signalled, not awaited here), so the
    # response may still read "running"; wait_idle below is what confirms it actually stopped.
    cancel = await client.post(f"/api/v1/runs/{run['id']}/cancel")
    assert cancel.status_code == 200, cancel.text

    await services.actors.wait_idle(timeout=10)

    dA, dB = await thread_detail(client, tA["id"]), await thread_detail(client, tB["id"])
    # cancelled before eng ever replied; a system notice explains the interruption instead.
    assert [m["content"] for m in dA["messages"]] == ["@eng go", "@eng run was cancelled."]
    assert statuses(await runs_for(client, tA["id"])) == ["cancelled"]
    assert [m["content"] for m in dB["messages"]] == ["@rev go", "Reviewed, all good."]
    assert statuses(await runs_for(client, tB["id"])) == ["completed"]
    assert dA["active"] is False and dB["active"] is False
