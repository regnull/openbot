from datetime import UTC, datetime, timedelta

from langchain_core.messages import AIMessage, HumanMessage

from openbot.db.models import Message
from openbot.runtime.prompt import build_history, build_system_prompt
from tests.factories import bot_actor

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def msg(i, kind, name, content, actor_id=None):
    return Message(id=f"m{i}", thread_id="t", sender_kind=kind, sender_actor_id=actor_id, sender_name=name,
                   content=content, created_at=T0 + timedelta(seconds=i))


def test_history_perspective_and_merge():
    ms = [msg(1, "human", "You", "hi"), msg(2, "bot", "Rev", "sure", "rev"), msg(3, "bot", "Eng", "done", "eng"),
          msg(4, "system", "system", "note"), msg(5, "human", "You", "ok")]
    hist, older = build_history(ms, "eng", token_budget=10_000, max_messages=80)
    assert older == 0
    assert isinstance(hist[0], HumanMessage) and hist[0].content == "[You]: hi\n\n[Rev]: sure"
    assert isinstance(hist[1], AIMessage) and hist[1].content == "done"
    assert hist[2].content == "[system]: note\n\n[You]: ok"


def test_history_limits():
    ms = [msg(i, "human", "a", "x" * 400) for i in range(10)]
    hist, older = build_history(ms, "eng", token_budget=10_000, max_messages=3)
    assert older == 7 and hist[0].content.count("[a]:") == 3
    hist, older = build_history(ms, "eng", token_budget=250, max_messages=80)
    assert older == 8


def test_system_prompt_contents():
    bot = bot_actor("eng", name="Engineer", description="Builds", instructions="Be terse.")
    bot.id = "e"
    rev = bot_actor("rev", name="Reviewer", description="Reviews")
    rev.id = "r"
    off = bot_actor("off")
    off.id, off.enabled = "o", False
    p = build_system_prompt(bot=bot, all_bots=[bot, rev, off], participants=["You", "Reviewer"], memories=["prefers squash"],
                            workspace_root="/w", older_count=12, tool_names=["run_shell"],
                            default_bot_handle="chief_of_staff")
    assert "Be terse." in p and "@rev" in p and "@off" not in p and "prefers squash" in p
    assert "12 older messages" in p and "/w" in p and "ask_human" in p and "@eng" in p and "run_shell" in p
    assert "thread default bot" in p and "@chief_of_staff" in p
    assert "current directory/root for shell and file tools" in p and "omit working_directory" in p
    # Bots used to @-mention other bots while merely narrating ("handing this to @reviewer"), which
    # woke them for no reason. Spell out that @ is an imperative, not a way of naming a bot.
    assert ("Only write @handle when you want that bot to act now. When merely referring to a bot, "
            "use its plain name without @.") in p
    # The chief of staff used start_thread to delegate, which split the conversation into a new thread
    # nobody was watching. Hand-offs must stay in the current thread; start_thread is not for delegation.
    assert "Never use start_thread to delegate or hand off work from this thread" in p


def test_history_marks_the_messages_that_triggered_this_run():
    """Several bots may post between two of this bot's runs, and several trigger messages may be
    coalesced into one run. The model must not have to guess which messages it is answering."""
    ms = [msg(1, "human", "You", "hi"), msg(2, "bot", "Eng", "done", "eng"), msg(3, "bot", "Rev", "LGTM", "rev"),
          msg(4, "human", "You", "@eng ship it"), msg(5, "bot", "Rev", "@eng also bump version", "rev")]
    hist, _ = build_history(ms, "eng", token_budget=10_000, max_messages=80, trigger_ids={"m4", "m5"})
    assert hist[-1].content == "[Rev]: LGTM\n\n[You] (new): @eng ship it\n\n[Rev] (new): @eng also bump version"
    assert hist[0].content == "[You]: hi"
    # Without trigger ids nothing is marked (the resume path has no trigger messages).
    hist, _ = build_history(ms, "eng", token_budget=10_000, max_messages=80)
    assert "(new)" not in hist[-1].content


def test_system_prompt_explains_the_new_marker():
    bot = bot_actor("eng", name="Engineer", description="Builds", instructions="Be terse.")
    bot.id = "e"
    p = build_system_prompt(bot=bot, all_bots=[bot], participants=["You"], memories=[], workspace_root="/w",
                            older_count=0, tool_names=[])
    assert "(new)" in p


def test_history_flags_triggers_that_arrived_before_the_bots_last_reply():
    """A nag that arrived while the bot was mid-run is picked up after that run's reply is posted.
    Marked as a plain "(new)", the model redid the work it had just reported. Say it may be handled."""
    ms = [msg(1, "human", "You", "@eng go"), msg(2, "bot", "QA", "@eng please push the fixes", "qa"),
          msg(3, "bot", "Eng", "Pushed the fixes.", "eng"), msg(4, "bot", "Rev", "@eng also bump version", "rev")]
    hist, _ = build_history(ms, "eng", token_budget=10_000, max_messages=80, trigger_ids={"m2", "m4"})
    assert hist[0].content == ("[You]: @eng go\n\n[QA] (new, arrived before your last reply; it may already be handled): "
                               "@eng please push the fixes")
    assert hist[-1].content == "[Rev] (new): @eng also bump version"


def test_system_prompt_explains_single_handoff_and_stale_triggers():
    bot = bot_actor("eng", name="Engineer", description="Builds", instructions="Be terse.")
    bot.id = "e"
    p = build_system_prompt(bot=bot, all_bots=[bot], participants=["You"], memories=[], workspace_root="/w",
                            older_count=0, tool_names=[])
    assert "only the first @handle in your reply wakes a bot" in p
    assert "arrived before your last reply" in p
