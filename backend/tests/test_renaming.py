import pytest

from openbot.db.models import Thread
from openbot.runtime.delivery import create_thread, human_actor, post_message
from tests.factories import bot_actor
from tests.fakes import ai


@pytest.fixture(autouse=True)
async def _no_actor_runs(services):
    await services.actors.stop()


async def seed(services, *actors):
    async with services.session_factory() as session:
        session.add_all(actors)
        await session.commit()
        return actors


async def test_auto_rename_after_third_message_and_only_once(services, scripts):
    await seed(services, bot_actor("chief_of_staff"), bot_actor("eng"))
    scripts["chief_of_staff"] = [ai('  "Purposeful title"  ')]
    async with services.bus.subscribe(None) as queue:
        async with services.session_factory() as session:
            you = await human_actor(session)
            thread = await create_thread(services, session, title="Initial", handles=["eng"], created_by=you)
            for content in ("first", "second", "third"):
                await post_message(services, session, thread_id=thread.id, sender=you, content=content)

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


async def test_auto_rename_claim_remains_consumed_when_provider_fails(services, scripts):
    await seed(services, bot_actor("chief_of_staff"), bot_actor("eng"))
    scripts["chief_of_staff"] = [RuntimeError("provider unavailable")]
    async with services.session_factory() as session:
        you = await human_actor(session)
        thread = await create_thread(services, session, title="Initial", handles=["eng"], created_by=you)
        for content in ("first", "second", "third"):
            await post_message(services, session, thread_id=thread.id, sender=you, content=content)
    async with services.session_factory() as session:
        renamed = await session.get(Thread, thread.id)
        assert renamed.title == "Initial"
        assert renamed.auto_renamed is True
