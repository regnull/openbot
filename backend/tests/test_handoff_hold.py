"""A bot hands off only when it has nothing else waiting in the thread.

In a pipeline thread the engineer finished a PR and mentioned @reviewer while two clarifications
from the human were still queued in its inbox. It then ran those as a second task and mentioned
@reviewer again, so the reviewer got two review requests for one PR, reviewed it twice, and the
extra runs cascaded. The rule: while a bot has queued `message` items in the thread it is replying
in, its @mentions are held; the reply is posted, a system notice says so, and the bot handles the
waiting messages next.

The wake-up is not left to the model to remember: BotActor._release_held_handoffs delivers the held
request itself, unmodified, as soon as the sender's queue for that thread is empty -- unless a later
reply from the sender already reached the target for real, in which case the hold is superseded and
nothing more happens. This is what closes the loop when the sender's next reply does not re-mention
the target (it judged the request already covered, or simply had nothing more to say to it)."""
import asyncio

from sqlalchemy import select

from openbot.db.models import ActivityLog, Actor, InboxItem, Message, Run, ThreadParticipant
from openbot.runtime.actors import BotActor
from openbot.runtime.delivery import create_thread, human_actor, post_message
from openbot.runtime.prompt import build_system_prompt
from tests.conftest import build_test_services
from tests.factories import bot_actor
from tests.fakes import ScriptedChatModel, ai


async def seed(services, *actors):
    async with services.session_factory() as s:
        s.add_all(actors)
        await s.commit()
        return actors


async def items(services, actor_id, status=None):
    async with services.session_factory() as s:
        q = select(InboxItem).where(InboxItem.actor_id == actor_id).order_by(InboxItem.created_at)
        if status:
            q = q.where(InboxItem.status == status)
        return (await s.execute(q)).scalars().all()


async def messages(services, thread_id):
    async with services.session_factory() as s:
        return (await s.execute(select(Message).where(Message.thread_id == thread_id).order_by(Message.created_at))).scalars().all()


async def activity(services, event):
    async with services.session_factory() as s:
        return (await s.execute(select(ActivityLog).where(ActivityLog.event == event).order_by(ActivityLog.id))).scalars().all()


async def participant_ids(services, thread_id):
    async with services.session_factory() as s:
        return {p.actor_id for p in (await s.execute(select(ThreadParticipant).where(ThreadParticipant.thread_id == thread_id))).scalars()}


# --- delivery bookkeeping, no runs --------------------------------------------------------------------------

async def test_bot_handoff_is_held_while_it_has_queued_mail_in_the_thread(services):
    await services.actors.stop()
    eng, rev = await seed(services, bot_actor("eng"), bot_actor("rev"))
    async with services.session_factory() as s:
        you = await human_actor(s)
        t = await create_thread(services, s, title="t", handles=["eng", "rev"], created_by=you)
        first = await post_message(services, s, thread_id=t.id, sender=you, content="@eng build it")
        await post_message(services, s, thread_id=t.id, sender=you, content="@eng one more thing")   # queued: nobody picks
        res = await post_message(services, s, thread_id=t.id, sender=eng, content="Built it. @rev please review", hop=1)
    assert res.addressed == [] and res.held == ["rev"] and res.unaddressed is False
    assert res.message.meta["held_handoff"] == ["rev"] and res.message.mentions == [rev.id]   # the mention is still recorded
    assert await items(services, rev.id) == []
    assert len(await items(services, eng.id, "queued")) == 2 and first.items[0].status == "queued"
    msgs = await messages(services, t.id)
    notice = msgs[-1]
    assert notice.sender_kind == "system" and notice.meta["kind"] == "handoff_held"
    assert "@eng" in notice.content and "@rev" in notice.content and "2 newer message" in notice.content
    assert notice.created_at > res.message.created_at   # deterministic: the notice always sorts after the reply it explains
    # Mentions the sender (its own scoped history explains why it woke later) and the held target
    # (its scoped history includes this once it is woken); a system message wakes nobody regardless.
    assert set(notice.mentions) == {eng.id, rev.id}
    [row] = await activity(services, "message.handoff_held")
    assert row.thread_id == t.id and row.actor_id == eng.id and row.message_id == res.message.id
    assert row.detail["held"] == ["rev"] and len(row.detail["pending_item_ids"]) == 2
    # The mention is real even though the wake-up is held: rev is already a participant.
    assert rev.id in await participant_ids(services, t.id)
    async with services.session_factory() as s:
        you = await human_actor(s)
    you_items = await items(services, you.id)
    assert [i.message_id for i in you_items][-2:] == [res.message.id, notice.id]   # the human sees both


async def test_handoff_delivers_once_the_thread_inbox_is_empty(services):
    await services.actors.stop()
    eng, rev = await seed(services, bot_actor("eng"), bot_actor("rev"))
    async with services.session_factory() as s:
        you = await human_actor(s)
        t = await create_thread(services, s, title="t", handles=["eng", "rev"], created_by=you)
        res = await post_message(services, s, thread_id=t.id, sender=you, content="@eng build it")
        for it in res.items:
            it.status = "done"
        await s.commit()
        res = await post_message(services, s, thread_id=t.id, sender=eng, content="Built it. @rev please review", hop=1)
    assert [a.id for a in res.addressed] == [rev.id] and res.held == [] and "held_handoff" not in res.message.meta
    assert len(await items(services, rev.id)) == 1
    assert await activity(services, "message.handoff_held") == []


async def test_queued_mail_in_another_thread_does_not_hold(services):
    await services.actors.stop()
    eng, rev = await seed(services, bot_actor("eng"), bot_actor("rev"))
    async with services.session_factory() as s:
        you = await human_actor(s)
        t1 = await create_thread(services, s, title="t1", handles=["eng", "rev"], created_by=you)
        t2 = await create_thread(services, s, title="t2", handles=["eng", "rev"], created_by=you)
        await post_message(services, s, thread_id=t2.id, sender=you, content="@eng other work")
        res = await post_message(services, s, thread_id=t1.id, sender=eng, content="@rev review", hop=1)
    assert [a.id for a in res.addressed] == [rev.id]


async def test_human_mentions_are_never_held(services):
    await services.actors.stop()
    eng, rev = await seed(services, bot_actor("eng"), bot_actor("rev"))
    async with services.session_factory() as s:
        you = await human_actor(s)
        t = await create_thread(services, s, title="t", handles=["eng", "rev"], created_by=you)
        await post_message(services, s, thread_id=t.id, sender=eng, content="Note for the human", hop=1)   # queued for @you
        res = await post_message(services, s, thread_id=t.id, sender=you, content="@rev take a look")
    assert [a.id for a in res.addressed] == [rev.id] and res.held == []


async def test_held_handoff_does_not_count_as_a_hop_or_trip_the_limit(services):
    await services.actors.stop()
    services.settings.max_bot_hops = 1
    eng, _rev = await seed(services, bot_actor("eng"), bot_actor("rev"))
    async with services.session_factory() as s:
        you = await human_actor(s)
        t = await create_thread(services, s, title="t", handles=["eng", "rev"], created_by=you)
        await post_message(services, s, thread_id=t.id, sender=you, content="@eng go")
        res = await post_message(services, s, thread_id=t.id, sender=eng, content="@rev review", hop=1)
    assert res.held == ["rev"]
    assert [m.meta.get("kind") for m in await messages(services, t.id) if m.sender_kind == "system"] == ["handoff_held"]


# --- mechanical release: BotActor._release_held_handoffs, exercised directly ---------------------------------

async def hold(services, t, eng):
    """Queue a message for eng in `t`, then have eng reply mentioning @rev: held, since eng's queue
    for `t` is non-empty. Returns the held message."""
    async with services.session_factory() as s:
        you = await human_actor(s)
        await post_message(services, s, thread_id=t.id, sender=you, content="@eng one more thing")  # queued, nobody picks
        res = await post_message(services, s, thread_id=t.id, sender=eng, content="@rev review", hop=1)
    assert res.held == ["rev"]
    return res.message


async def test_release_delivers_the_original_held_message_when_nothing_later_covers_it(services):
    await services.actors.stop()
    eng, rev = await seed(services, bot_actor("eng"), bot_actor("rev"))
    async with services.session_factory() as s:
        you = await human_actor(s)
        t = await create_thread(services, s, title="t", handles=["eng", "rev"], created_by=you)
    held_msg = await hold(services, t, eng)
    async with services.session_factory() as s:  # eng "handles" the clarification without re-mentioning rev
        for it in await items(services, eng.id, "queued"):
            i = await s.get(InboxItem, it.id)
            i.status = "done"
        await s.commit()
    worker = BotActor(services.actors, eng.id)
    await worker._release_held_handoffs(t.id)
    rev_items = await items(services, rev.id)
    assert len(rev_items) == 1 and rev_items[0].message_id == held_msg.id and rev_items[0].status == "queued"
    [row] = await activity(services, "inbox.hold_released")
    assert row.thread_id == t.id and row.actor_id == rev.id and row.message_id == held_msg.id
    assert row.detail["held_by"] == "eng" and row.detail["target"] == "rev"


async def test_release_is_skipped_when_a_later_reply_already_reached_the_target(services):
    await services.actors.stop()
    eng, rev = await seed(services, bot_actor("eng"), bot_actor("rev"))
    async with services.session_factory() as s:
        you = await human_actor(s)
        t = await create_thread(services, s, title="t", handles=["eng", "rev"], created_by=you)
    held_msg = await hold(services, t, eng)
    async with services.session_factory() as s:
        for it in await items(services, eng.id, "queued"):
            i = await s.get(InboxItem, it.id)
            i.status = "done"
        await s.commit()
        # eng's queue is now empty, so this mention goes through normally, not held.
        fresh = await post_message(services, s, thread_id=t.id, sender=eng, content="Fixed. @rev ready.", hop=2)
    assert fresh.held == [] and [a.id for a in fresh.addressed] == [rev.id]
    worker = BotActor(services.actors, eng.id)
    await worker._release_held_handoffs(t.id)
    rev_items = await items(services, rev.id)
    assert len(rev_items) == 1 and rev_items[0].message_id == fresh.message.id and rev_items[0].message_id != held_msg.id
    assert await activity(services, "inbox.hold_released") == []


async def test_release_does_nothing_while_the_sender_still_has_queued_mail_in_the_thread(services):
    await services.actors.stop()
    eng, rev = await seed(services, bot_actor("eng"), bot_actor("rev"))
    async with services.session_factory() as s:
        you = await human_actor(s)
        t = await create_thread(services, s, title="t", handles=["eng", "rev"], created_by=you)
    await hold(services, t, eng)
    # the clarification that made this a hold is still "queued": eng has not caught up yet
    worker = BotActor(services.actors, eng.id)
    await worker._release_held_handoffs(t.id)
    assert await items(services, rev.id) == []
    assert await activity(services, "inbox.hold_released") == []


async def test_release_is_idempotent(services):
    await services.actors.stop()
    eng, rev = await seed(services, bot_actor("eng"), bot_actor("rev"))
    async with services.session_factory() as s:
        you = await human_actor(s)
        t = await create_thread(services, s, title="t", handles=["eng", "rev"], created_by=you)
    await hold(services, t, eng)
    async with services.session_factory() as s:
        for it in await items(services, eng.id, "queued"):
            i = await s.get(InboxItem, it.id)
            i.status = "done"
        await s.commit()
    worker = BotActor(services.actors, eng.id)
    await worker._release_held_handoffs(t.id)
    await worker._release_held_handoffs(t.id)
    assert len(await items(services, rev.id)) == 1
    assert len(await activity(services, "inbox.hold_released")) == 1


async def test_release_supersedes_an_earlier_hold_to_the_same_target_with_the_later_one(services):
    """Two holds to @rev without anything real reaching it in between: only the LATER request is
    delivered, so rev is not woken twice for what is, by then, the same conversation topic."""
    await services.actors.stop()
    eng, rev = await seed(services, bot_actor("eng"), bot_actor("rev"))
    async with services.session_factory() as s:
        you = await human_actor(s)
        t = await create_thread(services, s, title="t", handles=["eng", "rev"], created_by=you)
    first_hold = await hold(services, t, eng)
    async with services.session_factory() as s:  # eng handles that clarification, but a second one is already queued
        it = (await items(services, eng.id, "queued"))[0]
        row = await s.get(InboxItem, it.id)
        row.status = "done"
        you = await human_actor(s)
        await post_message(services, s, thread_id=t.id, sender=you, content="@eng and one more")   # queued again
        second_res = await post_message(services, s, thread_id=t.id, sender=eng, content="@rev review again", hop=1)
    assert second_res.held == ["rev"]
    async with services.session_factory() as s:
        for it in await items(services, eng.id, "queued"):
            row = await s.get(InboxItem, it.id)
            row.status = "done"
        await s.commit()
    worker = BotActor(services.actors, eng.id)
    await worker._release_held_handoffs(t.id)
    rev_items = await items(services, rev.id)
    assert len(rev_items) == 1 and rev_items[0].message_id == second_res.message.id and rev_items[0].message_id != first_hold.id


async def test_release_adds_the_target_as_a_participant_if_it_somehow_is_not_one(services):
    await services.actors.stop()
    eng, rev = await seed(services, bot_actor("eng"), bot_actor("rev"))
    async with services.session_factory() as s:
        you = await human_actor(s)
        t = await create_thread(services, s, title="t", handles=["eng"], created_by=you)   # rev not in the thread
    await hold(services, t, eng)
    assert rev.id in await participant_ids(services, t.id)   # already added at hold time (see post_message)
    async with services.session_factory() as s:
        p = (await s.execute(select(ThreadParticipant).where(
            ThreadParticipant.thread_id == t.id, ThreadParticipant.actor_id == rev.id))).scalar_one()
        await s.delete(p)   # simulate it having been removed some other way
        await s.commit()
        for it in await items(services, eng.id, "queued"):
            row = await s.get(InboxItem, it.id)
            row.status = "done"
        await s.commit()
    worker = BotActor(services.actors, eng.id)
    await worker._release_held_handoffs(t.id)
    assert rev.id in await participant_ids(services, t.id)
    assert len(await items(services, rev.id)) == 1


async def test_release_ignores_unknown_or_disabled_target_handles(services):
    """A held handle that no longer resolves to a bot (deleted, or a race this code should not choke
    on) is skipped rather than raising."""
    await services.actors.stop()
    eng, rev = await seed(services, bot_actor("eng"), bot_actor("rev"))
    async with services.session_factory() as s:
        you = await human_actor(s)
        t = await create_thread(services, s, title="t", handles=["eng", "rev"], created_by=you)
    await hold(services, t, eng)
    async with services.session_factory() as s:
        await s.delete(await s.get(Actor, rev.id))
        for it in await items(services, eng.id, "queued"):
            row = await s.get(InboxItem, it.id)
            row.status = "done"
        await s.commit()
    worker = BotActor(services.actors, eng.id)
    await worker._release_held_handoffs(t.id)   # must not raise
    assert await activity(services, "inbox.hold_released") == []


# --- end to end: the engineer finishes the queued work, then hands off once ---------------------------------

class Slow:
    """Scripted replies with a pause before the first, wide enough to post into the running bot's inbox."""

    def __init__(self, replies, delay=0.6):
        self.replies, self.delay, self.first = iter(replies), delay, True

    def __iter__(self):
        return self

    def __next__(self):
        import time
        if self.first:
            self.first = False
            time.sleep(self.delay)          # in the model's executor thread; the event loop keeps running
        return next(self.replies)


async def until(check, timeout=5.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if (r := await check()):
            return r
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met")


async def test_engineer_handles_queued_mail_before_the_handoff_reaches_the_reviewer(settings):
    ScriptedChatModel.seen.clear()
    services = await build_test_services(settings, {"rev": [ai("Reviewed, all good.")]})
    scripts = {"eng": Slow([ai("PR opened. @rev please review."), ai("Folded the clarification in. @rev ready for review.")])}
    base_factory = services.model_factory
    services.model_factory = lambda actor: ScriptedChatModel(messages=scripts[actor.handle]) if actor.handle in scripts else base_factory(actor)
    async with services.session_factory() as s:
        s.add_all([bot_actor("eng"), bot_actor("rev")])
        await s.commit()
        you = await human_actor(s)
        t = await create_thread(services, s, title="t", handles=["eng", "rev"], created_by=you)
        await post_message(services, s, thread_id=t.id, sender=you, content="@eng build the cursor")
    await services.actors.start()

    async def eng_running():
        async with services.session_factory() as s:
            return (await s.execute(select(Run).where(Run.status == "running"))).scalar_one_or_none()
    await until(eng_running)
    async with services.session_factory() as s:
        you = await human_actor(s)
        await post_message(services, s, thread_id=t.id, sender=you, content="@eng actually make it orange")
    await services.actors.wait_idle(timeout=10)

    async with services.session_factory() as s:
        runs = (await s.execute(select(Run).order_by(Run.created_at))).scalars().all()
        eng = (await s.execute(select(InboxItem).where(InboxItem.kind == "message"))).scalars().all()
    by_handle = {}
    async with services.session_factory() as s:
        from openbot.db.models import Actor
        for a in (await s.execute(select(Actor))).scalars():
            by_handle[a.id] = a.handle
    assert [by_handle[r.actor_id] for r in runs] == ["eng", "eng", "rev"]
    assert all(r.status == "completed" for r in runs)
    msgs = await messages(services, t.id)
    # The clarification lands while the engineer is still working, so it precedes the engineer's first reply.
    assert [(m.sender_name, m.content) for m in msgs] == [
        ("You", "@eng build the cursor"),
        ("You", "@eng actually make it orange"),
        ("Eng", "PR opened. @rev please review."),
        ("system", msgs[3].content),
        ("Eng", "Folded the clarification in. @rev ready for review."),
        ("Rev", "Reviewed, all good."),
    ]
    assert msgs[2].meta["held_handoff"] == ["rev"]
    assert msgs[3].sender_kind == "system" and msgs[3].meta["kind"] == "handoff_held" and "@eng has 1 newer message" in msgs[3].content
    assert "held_handoff" not in msgs[4].meta
    # The reviewer was woken exactly once, by the second reply -- the mechanical release found the
    # hold already covered by it and delivered nothing extra.
    rev_items = [i for i in eng if by_handle[i.actor_id] == "rev"]
    assert len(rev_items) == 1 and rev_items[0].message_id == msgs[4].id
    assert await activity(services, "inbox.hold_released") == []
    # The engineer's second run saw the notice and the clarification, marked as arrived before its reply.
    second = next(m for m in ScriptedChatModel.seen if any("make it orange" in x.content for x in m if x.type == "human"))
    history = "\n".join(x.content for x in second if x.type == "human")
    assert "[system]: @eng has 1 newer message" in history
    assert "[You] (new, arrived before your last reply; it may already be handled): @eng actually make it orange" in history
    await services.actors.stop()


def test_system_prompt_explains_held_handoffs_and_message_priority():
    bot = bot_actor("eng", name="Engineer")
    bot.id = "e"
    p = build_system_prompt(bot=bot, all_bots=[bot], participants=["You"], memories=[], workspace_root="/w", older_count=0, tool_names=[])
    assert "a reply that mentions another bot does not wake it" in p
    assert "later messages take priority over earlier ones" in p
    # Not "mention the bot again" as a requirement: the platform delivers the held request whether or
    # not the model remembers to. This is what keeps the rule from contradicting the stale-marker rule
    # ("answer in one sentence and stop") -- stopping early no longer drops the hand-off.
    assert "do not need to remember to re-mention the held bot" in p
    assert "delivers your original request to it automatically" in p
    assert "whether or not your later reply mentions it again" in p
