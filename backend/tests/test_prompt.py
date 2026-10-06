from datetime import UTC, datetime, timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from openbot.db.models import Message
from openbot.runtime.prompt import build_history, build_system_prompt, build_system_prompt_parts
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
    assert "current directory/root for shell and file tools" in p
    # Bots used to @-mention other bots while merely narrating ("handing this to @reviewer"), which
    # woke them for no reason. Spell out that @ is an imperative, not a way of naming a bot.
    assert ("Only write @handle when you want that bot to act now. When merely referring to a bot, "
            "use its plain name without @.") in p
    # There is no tool for starting a separate thread; hand-offs must stay in the current one.
    assert "There is no way to start a separate thread" in p
    # Every reply must hand off explicitly, even bot-to-bot, unless the thread lead is done or needs
    # the human; an unsure bot defers to the thread lead rather than guessing or dropping the ball.
    assert "End every reply with a handoff" in p and "Never hand off to yourself" in p
    assert "thread lead (@chief_of_staff)" in p
    # Scheduling a follow-up message keeps the thread from being considered finished.
    assert "schedule_message" in p and "active for as long as it has a message scheduled" in p
    # Third-party comments/notes must be signed so the handle doesn't tag an unrelated user there.
    assert 'If the system does not support Markdown, sign it as "OpenBot - `@eng`".' in p


def test_system_prompt_template_uses_only_the_supported_placeholders():
    from string import Template

    from openbot.runtime import prompt as prompt_module

    actual = frozenset(Template(prompt_module.SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")).get_identifiers())
    stable = frozenset(Template(prompt_module.STABLE_SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")).get_identifiers())
    dynamic = frozenset(Template(prompt_module.DYNAMIC_SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")).get_identifiers())
    assert actual == prompt_module._SYSTEM_PROMPT_FIELDS
    assert stable | dynamic == prompt_module._SYSTEM_PROMPT_FIELDS
    assert "repository_instructions" not in actual


def test_system_prompt_is_loaded_from_the_packaged_markdown_template():
    from openbot.runtime import prompt as prompt_module

    assert prompt_module.SYSTEM_PROMPT_FILE.name == "system_prompt.md"
    assert prompt_module.SYSTEM_PROMPT_FILE.is_file()
    assert build_system_prompt(
        bot=bot_actor("eng", name="Engineer", instructions="Be terse."), all_bots=[], participants=[],
        memories=[], workspace_root="/w", older_count=0, tool_names=[]
    ).startswith("You are Engineer (@eng), a persistent AI bot on the OpenBot platform.")


def test_system_prompt_rejects_missing_template(monkeypatch, tmp_path):
    from openbot.runtime import prompt as prompt_module

    monkeypatch.setattr(prompt_module, "SYSTEM_PROMPT_FILE", tmp_path / "missing.md")
    with pytest.raises(RuntimeError, match="Unable to load shared system prompt"):
        prompt_module._load_system_prompt_template()


def test_system_prompt_rejects_invalid_template(monkeypatch, tmp_path):
    from openbot.runtime import prompt as prompt_module

    invalid = tmp_path / "invalid.md"
    invalid.write_text("${bot_name} ${unknown}", encoding="utf-8")
    monkeypatch.setattr(prompt_module, "SYSTEM_PROMPT_FILE", invalid)
    with pytest.raises(RuntimeError, match="unexpected placeholders: unknown"):
        prompt_module._load_system_prompt_template()


def test_system_prompt_template_is_fixed_at_import(monkeypatch, tmp_path):
    """The template is read once, when the code that fills it is imported. Bots edit OpenBot's own
    source in the workspace, so a half-applied change to system_prompt.md (a new placeholder the
    running code doesn't fill yet) must not break every run of the live instance."""
    from openbot.runtime import prompt as prompt_module

    edited = tmp_path / "system_prompt.md"
    edited.write_text("${bot_name} ${not_filled_by_this_code}", encoding="utf-8")
    monkeypatch.setattr(prompt_module, "SYSTEM_PROMPT_FILE", edited)
    assert build_system_prompt(
        bot=bot_actor("eng", name="Engineer"), all_bots=[], participants=[],
        memories=[], workspace_root="/w", older_count=0, tool_names=[]
    ).startswith("You are Engineer (@eng)")


def test_system_prompt_lead_note_omitted_without_a_default_bot():
    bot = bot_actor("eng", name="Engineer", description="Builds", instructions="Be terse.")
    bot.id = "e"
    p = build_system_prompt(bot=bot, all_bots=[bot], participants=["You"], memories=[],
                            workspace_root="/w", older_count=0, tool_names=[])
    assert "hand off to the thread lead instead of guessing" in p and "thread lead (@" not in p


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
    # A hint ("check whether that reply already covers it") did not stop a model from redoing a
    # seven-minute review; the marker now comes with a rule and an exit.
    assert "Before using any tool, compare it with your last reply" in p
    assert "answer with one short sentence saying so and stop; do not redo or re-verify the work" in p


def test_system_prompt_injects_lead_context_only_for_lead():
    lead = bot_actor("chief_of_staff", name="Chief")
    lead.id = "lead"
    delegate = bot_actor("eng", name="Engineer")
    delegate.id = "eng"
    lead_prompt = build_system_prompt(bot=lead, all_bots=[lead, delegate], participants=["You"], memories=[], workspace_root="/w", older_count=0, tool_names=[], default_bot_handle="chief_of_staff")
    delegate_prompt = build_system_prompt(bot=delegate, all_bots=[lead, delegate], participants=["You"], memories=[], workspace_root="/w", older_count=0, tool_names=[], default_bot_handle="chief_of_staff")
    context = "thread lead for this thread is @chief_of_staff. If you are not sure about the handoff, do a handoff to the thread lead"
    instructions = "you are the lead for this thread. When human talks to you, follow this process"
    assert context in lead_prompt and instructions in lead_prompt
    assert context in delegate_prompt and instructions not in delegate_prompt


def test_history_marks_the_bots_own_interrupted_reply():
    cut = msg(2, "bot", "Eng", "half a", "eng")
    cut.meta = {"interrupted": True}
    empty = msg(3, "bot", "Eng", "", "eng")
    empty.meta = {"interrupted": True}
    hist, _ = build_history([msg(1, "human", "You", "go"), cut, empty, msg(4, "bot", "Eng", "done", "eng")], "eng",
                            token_budget=10_000, max_messages=80)
    assert [m.content for m in hist[1:]] == ["half a\n\n[interrupted by the user]", "[interrupted by the user]", "done"]


def test_repository_instructions_are_loaded_from_nearest_parent_with_agents_precedence(tmp_path):
    from openbot.runtime.prompt import load_repository_instructions

    repo = tmp_path / "repo"
    nested = repo / "src"
    nested.mkdir(parents=True)
    (repo / "CLAUDE.md").write_text("claude", encoding="utf-8")
    (repo / "AGENTS.md").write_text("agents", encoding="utf-8")
    assert load_repository_instructions(str(repo), enabled=True, start_directory=str(nested)) == "agents"


def test_repository_instructions_searches_upward_and_caps_content(tmp_path):
    from openbot.runtime.prompt import load_repository_instructions

    repo = tmp_path / "repo"
    nested = repo / "a" / "b"
    nested.mkdir(parents=True)
    content = "x" * 40_000
    (repo / "CLAUDE.md").write_text(content, encoding="utf-8")
    loaded = load_repository_instructions(str(repo), enabled=True, start_directory=str(nested))
    assert len(loaded) == 32_000


def test_repository_instructions_stop_at_workspace_root(tmp_path):
    from openbot.runtime.prompt import load_repository_instructions

    workspace = tmp_path / "workspace"
    nested = workspace / "repo" / "src"
    nested.mkdir(parents=True)
    (tmp_path / "AGENTS.md").write_text("outside", encoding="utf-8")
    (workspace / "repo" / "CLAUDE.md").write_text("inside", encoding="utf-8")

    assert load_repository_instructions(str(workspace / "repo"), enabled=True, start_directory=str(nested)) == "inside"
    (workspace / "repo" / "CLAUDE.md").unlink()
    assert load_repository_instructions(str(workspace / "repo"), enabled=True, start_directory=str(nested)) == ""


def test_repository_instructions_can_be_disabled(tmp_path):
    from openbot.runtime.prompt import load_repository_instructions

    (tmp_path / "AGENTS.md").write_text("secret", encoding="utf-8")
    assert load_repository_instructions(str(tmp_path), enabled=False) == ""


def test_repository_instructions_are_rendered_through_validated_template(tmp_path):
    bot = bot_actor("eng", name="Engineer", instructions="Be terse.")
    (tmp_path / "AGENTS.md").write_text("Use the repository rules.", encoding="utf-8")
    bot.bot.load_repository_instructions = True

    prompt = build_system_prompt(bot=bot, all_bots=[bot], participants=[], memories=[],
                                 workspace_root=str(tmp_path), older_count=0, tool_names=[])

    assert "# Repository instructions\nUse the repository rules." in prompt
    assert "${repository_instructions}" not in prompt


def test_system_prompt_parts_keep_stable_prefix_separate():
    bot = bot_actor("eng", name="Engineer", description="Builds", instructions="Be terse.")
    bot.id = "e"
    stable, dynamic = build_system_prompt_parts(bot=bot, all_bots=[bot], participants=["You"], memories=["prefers_dynamic_memory"],
                                                workspace_root="/w", older_count=2, tool_names=["run_shell"])
    assert "Engineer" in stable and "Be terse." in stable
    assert "prefers_dynamic_memory" not in stable and "older messages" not in stable
    assert "m" in dynamic and "older messages" in dynamic
    assert build_system_prompt(bot=bot, all_bots=[bot], participants=["You"], memories=["prefers_dynamic_memory"],
                               workspace_root="/w", older_count=2, tool_names=["run_shell"]) == stable + dynamic
