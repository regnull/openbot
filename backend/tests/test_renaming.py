import asyncio
import logging
from typing import Any

import pytest_asyncio
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from openbot.db.models import Thread
from openbot.runtime.delivery import create_thread, human_actor, post_message
from openbot.runtime.renaming import finish_renames
from tests.factories import bot_actor
from tests.fakes import ScriptedChatModel, ai


@pytest_asyncio.fixture(autouse=True)
async def _no_actor_runs(services):
    await services.actors.stop()


async def seed(services, *actors):
    async with services.session_factory() as session:
        session.add_all(actors)
        await session.commit()
        return actors


class GatedModel(ScriptedChatModel):
    """Answers only once `gate` is set, like a provider that is slow to reply."""

    gate: Any
    calls: Any

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls.append(messages)
        await self.gate.wait()
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="Late title"))])


async def gated_thread(services, posts):
    """A thread with `posts` messages whose title model has been asked but has not answered yet."""
    await seed(services, bot_actor("chief_of_staff"), bot_actor("eng"))
    gate, calls = asyncio.Event(), []
    services.model_factory = lambda actor: GatedModel(messages=iter(()), gate=gate, calls=calls)
    async with services.session_factory() as session:
        you = await human_actor(session)
        thread = await create_thread(services, session, title="Initial", handles=["eng"], created_by=you)
        for n in range(posts):
            await asyncio.wait_for(post_message(services, session, thread_id=thread.id, sender=you, content=f"post {n}"), 2)
    return thread, gate, calls


async def stored(services, thread):
    async with services.session_factory() as session:
        return await session.get(Thread, thread.id)


async def test_auto_rename_after_third_message_and_only_once(services, scripts):
    await seed(services, bot_actor("chief_of_staff"), bot_actor("eng"))
    scripts["chief_of_staff"] = [ai('  "Purposeful title"  ')]
    async with services.bus.subscribe(None) as queue:
        async with services.session_factory() as session:
            you = await human_actor(session)
            thread = await create_thread(services, session, title="Initial", handles=["eng"], created_by=you)
            for content in ("first", "second", "third"):
                await post_message(services, session, thread_id=thread.id, sender=you, content=content)
        await finish_renames(services)

        async with services.session_factory() as session:
            renamed = await session.get(Thread, thread.id)
            assert renamed.title == "Purposeful title"
            assert renamed.auto_renamed is True
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
    updates = [event for event in events if event["event"] == "thread.updated"]
    assert len(updates) == 1
    assert updates[0]["data"]["title"] == "Purposeful title"


async def test_auto_rename_claim_remains_consumed_when_provider_fails(services, scripts, caplog):
    await seed(services, bot_actor("chief_of_staff"), bot_actor("eng"))
    scripts["chief_of_staff"] = [RuntimeError("provider unavailable")]
    async with services.session_factory() as session:
        you = await human_actor(session)
        thread = await create_thread(services, session, title="Initial", handles=["eng"], created_by=you)
        for content in ("first", "second", "third"):
            await post_message(services, session, thread_id=thread.id, sender=you, content=content)
    with caplog.at_level(logging.ERROR, logger="openbot.runtime.renaming"):
        await finish_renames(services)
    async with services.session_factory() as session:
        renamed = await session.get(Thread, thread.id)
        assert renamed.title == "Initial"
        assert renamed.auto_renamed is True
    # The failure happens in a background task now; it must still reach the log.
    [record] = [r for r in caplog.records if "automatic thread rename failed" in r.getMessage()]
    assert "provider unavailable" in str(record.exc_info[1])


async def test_post_does_not_wait_for_the_title_model(services):
    thread, gate, calls = await gated_thread(services, posts=3)
    waiting = await stored(services, thread)
    assert (waiting.title, waiting.auto_renamed, len(calls)) == ("Initial", True, 1)
    gate.set()
    await finish_renames(services)
    assert (await stored(services, thread)).title == "Late title"
    assert not services._rename_tasks


async def test_posts_during_a_pending_rename_do_not_ask_for_another_title(services):
    thread, gate, calls = await gated_thread(services, posts=5)
    assert len(calls) == 1 and len(services._rename_tasks) == 1
    gate.set()
    await finish_renames(services)
    assert (await stored(services, thread)).title == "Late title" and len(calls) == 1


async def test_finish_renames_gives_up_on_a_title_that_does_not_arrive(services):
    thread, _gate, _calls = await gated_thread(services, posts=3)
    await asyncio.wait_for(finish_renames(services, timeout=0.05), 2)
    assert not services._rename_tasks
    renamed = await stored(services, thread)
    assert (renamed.title, renamed.auto_renamed) == ("Initial", True)


async def test_a_post_that_is_not_delivered_does_not_rename(services, scripts):
    eng, _ = await seed(services, bot_actor("eng"), bot_actor("chief_of_staff"))
    scripts["chief_of_staff"] = [ai("Too early")]
    async with services.session_factory() as session:
        you = await human_actor(session)
        thread = await create_thread(services, session, title="Initial", handles=["eng"], created_by=you)
        await post_message(services, session, thread_id=thread.id, sender=you, content="first")
        await post_message(services, session, thread_id=thread.id, sender=you, content="second")
        await post_message(services, session, thread_id=thread.id, sender=eng, content="cut off", deliver=False)
    async with services.session_factory() as session:
        thread = await session.get(Thread, thread.id)
        assert (thread.title, thread.auto_renamed) == ("Initial", False)
