import pytest
from sqlalchemy import select

from openbot.db.models import InboxItem, Message, ThreadParticipant
from openbot.runtime.delivery import create_thread, human_actor, post_message
from tests.factories import bot_actor, external_actor


@pytest.fixture(autouse=True)
async def _no_actor_runs(services):
    """Delivery bookkeeping is asserted on its own: keep the actor system from picking the items up."""
    await services.actors.stop()


async def seed(services, *actors):
    async with services.session_factory() as s:
        s.add_all(actors)
        await s.commit()
        return actors


async def items(services, actor_id=None):
    async with services.session_factory() as s:
        q = select(InboxItem).order_by(InboxItem.created_at)
        if actor_id:
            q = q.where(InboxItem.actor_id == actor_id)
        return (await s.execute(q)).scalars().all()


async def test_post_creates_items_for_bots_and_notifies_humans(services):
    eng, rev, ci = await seed(services, bot_actor("eng"), bot_actor("rev"), external_actor("ci"))
    async with services.bus.subscribe(None) as q:
        async with services.session_factory() as s:
            you = await human_actor(s)
            t = await create_thread(services, s, title="t", handles=["eng", "ci"], created_by=you)
            res = await post_message(services, s, thread_id=t.id, sender=you, content="hi @rev")
        assert [a.handle for a in res.addressed] == ["rev"] and res.unaddressed is False
        assert res.message.hop == 0 and res.message.mentions == [rev.id] and res.message.sender_kind == "human"
        events = [q.get_nowait()["event"] for _ in range(q.qsize())]
        assert events.count("message.created") == 1 and events.count("inbox.updated") == 2
    async with services.session_factory() as s:
        parts = {p.actor_id for p in (await s.execute(select(ThreadParticipant).where(ThreadParticipant.thread_id == t.id))).scalars()}
    assert parts == {you.id, eng.id, ci.id, rev.id}
    its = await items(services)
    assert {(i.actor_id, i.kind, i.status) for i in its} == {(rev.id, "message", "queued"), (ci.id, "message", "queued")}
    assert (await services.store.asearch(("threads", t.id, "messages"), query="hi"))[0].key == res.message.id


async def test_default_bot_routes_unmentioned_human_messages(services):
    chief, _eng, _rev = await seed(services, bot_actor("chief_of_staff"), bot_actor("eng"), bot_actor("rev"))
    async with services.session_factory() as s:
        you = await human_actor(s)
        t = await create_thread(services, s, title="t", handles=["eng", "rev"], created_by=you)
        assert t.default_bot_actor_id == chief.id
        res = await post_message(services, s, thread_id=t.id, sender=you, content="hello")
        assert [a.id for a in res.addressed] == [chief.id]
        assert res.unaddressed is False


async def test_changed_default_and_explicit_mention_precedence(services):
    chief, eng, rev = await seed(services, bot_actor("chief_of_staff"), bot_actor("eng"), bot_actor("rev"))
    async with services.session_factory() as s:
        you = await human_actor(s)
        t = await create_thread(services, s, title="t", handles=["eng", "rev"], created_by=you, default_bot_handle="rev")
        assert t.default_bot_actor_id == rev.id
        defaulted = await post_message(services, s, thread_id=t.id, sender=you, content="hello")
        assert [a.id for a in defaulted.addressed] == [rev.id]
        explicit = await post_message(services, s, thread_id=t.id, sender=you, content="@eng please handle")
        assert [a.id for a in explicit.addressed] == [eng.id]
        assert chief.id not in [a.id for a in explicit.addressed]


async def test_single_bot_legacy_default_and_unaddressed_without_default(services):
    eng, _rev = await seed(services, bot_actor("eng"), bot_actor("rev"))
    async with services.session_factory() as s:
        you = await human_actor(s)
        t = await create_thread(services, s, title="t", handles=["eng"], created_by=you)
        res = await post_message(services, s, thread_id=t.id, sender=you, content="hello")
        assert [a.id for a in res.addressed] == [eng.id]
        t2 = await create_thread(services, s, title="t", handles=["eng", "rev"], created_by=you)
        res = await post_message(services, s, thread_id=t2.id, sender=you, content="hello")
        assert res.addressed == [] and res.unaddressed is True


async def test_bot_reply_hops_and_limit(services):
    services.settings.max_bot_hops = 2
    eng, rev = await seed(services, bot_actor("eng"), bot_actor("rev"))
    async with services.session_factory() as s:
        you = await human_actor(s)
        t = await create_thread(services, s, title="t", handles=["eng", "rev"], created_by=you)
        await post_message(services, s, thread_id=t.id, sender=you, content="@eng go")
        r2 = await post_message(services, s, thread_id=t.id, sender=eng, content="@rev review", hop=1)
        assert r2.message.hop == 1 and [a.id for a in r2.addressed] == [rev.id]
        r3 = await post_message(services, s, thread_id=t.id, sender=rev, content="@eng fix", hop=2)
        assert r3.addressed == []
        msgs = (await s.execute(select(Message).where(Message.thread_id == t.id).order_by(Message.created_at))).scalars().all()
        assert msgs[-1].sender_kind == "system" and "hop limit" in msgs[-1].content
        await post_message(services, s, thread_id=t.id, sender=rev, content="@eng again", hop=2)
        n_sys = sum(1 for m in (await s.execute(select(Message).where(Message.thread_id == t.id))).scalars() if m.sender_kind == "system")
        assert n_sys == 1
        r5 = await post_message(services, s, thread_id=t.id, sender=you, content="@eng human here")
        assert [a.id for a in r5.addressed] == [eng.id]
    eng_items = await items(services, eng.id)
    assert [i.kind for i in eng_items] == ["message", "message"]  # "go" and "human here"; the hop-limited ones were dropped
    you_items = await items(services, you.id)
    assert len(you_items) == 4  # two bot messages, one notice... and the second "again" bot message


async def test_unknown_handles(services):
    await seed(services, bot_actor("eng"))
    async with services.session_factory() as s:
        you = await human_actor(s)
        with pytest.raises(ValueError):
            await create_thread(services, s, title="t", handles=["ghost"], created_by=you)
        t = await create_thread(services, s, title="t", handles=["eng"], created_by=you)
        with pytest.raises(ValueError):
            await post_message(services, s, thread_id=t.id, sender=you, content="x", to_handles=["ghost"])
        with pytest.raises(LookupError):
            await post_message(services, s, thread_id="nope", sender=you, content="x")
