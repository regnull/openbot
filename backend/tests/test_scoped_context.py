"""How much of a thread each bot sees (docs/architecture.md §6).

The thread's default bot (or the only bot in the thread) gets the full unroll. Every other bot sees
only the messages addressed to it and its own earlier replies: a hand-off must be self-contained,
and read_history / recall_messages fetch the rest when it is not.
"""
from sqlalchemy import select

from openbot.db.models import Actor
from openbot.runtime.delivery import create_thread, human_actor, post_message
from openbot.seed import DEMO_BOTS
from tests.conftest import build_test_services
from tests.factories import bot_actor
from tests.fakes import ScriptedChatModel, ai


def _calls_for(handle: str) -> list[list]:
    """Model calls made by the bot with this handle, oldest first."""
    return [call for call in ScriptedChatModel.seen if call and call[0].type == "system" and f"(@{handle})" in call[0].content]


def _texts(call) -> str:
    return "\n".join(str(m.content) for m in call if m.type != "system")


async def _post(services, thread_id, sender, content):
    async with services.session_factory() as s:
        sender_row = await human_actor(s) if sender == "you" else (await s.execute(select(Actor).where(Actor.handle == sender))).scalar_one()
        return await post_message(services, s, thread_id=thread_id, sender=sender_row, content=content)


async def test_default_bot_sees_everything_and_delegates_see_only_their_slice(settings):
    ScriptedChatModel.seen.clear()
    scripts = {
        "chief_of_staff": [ai("@eng implement the widget in src/w.py; acceptance: tests pass; report the PR number back")],
        "eng": [ai("Opened PR 31 for the widget. @rev please review"), ai("Fixed the lint in PR 31.")],
        "rev": [ai("@eng PR 31: fix the lint error in src/w.py line 3")],
    }
    services = await build_test_services(settings, scripts)
    async with services.session_factory() as s:
        s.add_all([bot_actor("chief_of_staff", description="coordinates"), bot_actor("eng", description="builds"), bot_actor("rev", description="reviews")])
        await s.commit()
        you = await human_actor(s)
        t = await create_thread(services, s, title="t", handles=["chief_of_staff", "eng", "rev"], created_by=you, default_bot_handle="chief_of_staff")
    await services.actors.start()
    await _post(services, t.id, "you", "please build me a widget")
    await services.actors.wait_idle()
    await services.actors.stop()

    eng_calls = _calls_for("eng")
    assert len(eng_calls) == 2
    first, second = _texts(eng_calls[0]), _texts(eng_calls[1])
    # First run: only the chief's hand-off, not the human's request to the chief.
    assert "implement the widget" in first and "please build me a widget" not in first
    # Second run: everything addressed to it so far plus its own earlier reply; still not the human's request.
    assert "fix the lint error" in second and "Opened PR 31" in second and "implement the widget" in second
    assert "please build me a widget" not in second
    assert "(new): @eng PR 31" in second                      # the trigger is still marked
    sys_prompt = eng_calls[1][0].content
    assert "only the messages addressed to you" in sys_prompt and "read_history" in sys_prompt and "recall_messages" in sys_prompt
    assert "other messages exist" in sys_prompt and "The full thread history is shown" not in sys_prompt

    chief_calls = _calls_for("chief_of_staff")
    assert chief_calls and "please build me a widget" in _texts(chief_calls[0])
    assert "The full thread history is shown" in chief_calls[0][0].content


async def test_the_only_bot_in_a_thread_gets_the_full_history(settings):
    ScriptedChatModel.seen.clear()
    services = await build_test_services(settings, {"eng": [ai("noted"), ai("done")]})
    async with services.session_factory() as s:
        s.add(bot_actor("eng", description="builds"))
        await s.commit()
        you = await human_actor(s)
        t = await create_thread(services, s, title="t", handles=["eng"], created_by=you)
    await services.actors.start()
    await _post(services, t.id, "you", "context: the repo uses squash merges")   # no mention: routed to the only bot
    await services.actors.wait_idle()
    await _post(services, t.id, "you", "now do the thing")
    await services.actors.wait_idle()
    await services.actors.stop()
    calls = _calls_for("eng")
    assert len(calls) == 2 and "squash merges" in _texts(calls[1]) and "The full thread history is shown" in calls[1][0].content


def test_seeded_instructions_explain_the_scoped_view():
    bots = {b["handle"]: b for b in DEMO_BOTS}
    chief = bots["chief_of_staff"]["instructions"]
    assert "only the message you address to them" in chief and "self-contained" in chief
    for h in ("engineer", "reviewer", "qa"):
        text = bots[h]["instructions"]
        assert "only the messages addressed to you" in text and "read_history" in text, h
