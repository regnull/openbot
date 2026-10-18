"""Skills: SKILL.md discovery, front-matter parsing, per-bot enablement and the load_skill tool.

Covers the pieces behind issue #252: workspace/state-dir discovery (workspace roots shadow the
state dir), front-matter validation, the prompt section (ids + descriptions only), the
`load_skill` tool (errors for unknown/none-enabled skills, sibling file listing), the runner
wiring (skills only in the prompt when the bot has the tool), and the API's unknown-skill 422.
"""

import pytest
import pytest_asyncio
from langchain.tools import ToolRuntime

from openbot.runtime.delivery import create_thread, human_actor
from openbot.skills import (
    MAX_SKILLS,
    SkillError,
    discover_skills,
    enabled_skills,
    parse_skill_md,
    skills_section,
)
from openbot.tools.builtin.skills import MAX_FILES, load_skill
from openbot.tools.context import RunContext
from tests.factories import bot_actor
from tests.fakes import ScriptedChatModel, ai
from tests.test_runner import make

SKILL_MD = """---
name: Git Rebasing
description: Clean up commit history with an interactive rebase, safely.
---

# Git Rebasing

Run `git rebase -i HEAD~3`, pick/squash lines, force-push only unpushed branches.
"""

OTHER_MD = """---
name: Deep Review
description: A second skill from the state directory.
---

Body of deep review.
"""


def write_skill(ws, ident, content=SKILL_MD, filename="SKILL.md"):
    d = ws / "skills" / ident
    d.mkdir(parents=True)
    (d / filename).write_text(content, encoding="utf-8")
    return d


def sibling(ws, ident, name, content="#!/bin/sh\necho helper\n"):
    p = ws / "skills" / ident / name
    p.write_text(content, encoding="utf-8")
    return p


class FakeSettings:
    def __init__(self, state_dir=None):
        self.state_dir = state_dir


# --- discovery ---------------------------------------------------------------


def test_discovery_finds_both_layouts_and_skips_non_skill_files(tmp_path):
    write_skill(tmp_path, "py")                      # skills/py/SKILL.md -> id "py"
    (tmp_path / "skills" / "handbook.md").write_text(SKILL_MD, encoding="utf-8")
    sibling(tmp_path, "py", "scripts", "helper.sh")  # nested non-md: supporting file, not a skill
    skills = discover_skills(tmp_path)
    ids = {s.id for s in skills}
    assert ids == {"py", "handbook"}


def test_discovery_parses_front_matter_into_id_name_description(tmp_path):
    write_skill(tmp_path, "py")
    (skill,) = discover_skills(tmp_path)
    assert (skill.id, skill.name) == ("py", "Git Rebasing")
    assert "interactive rebase" in skill.description


def test_workspace_roots_shadow_the_state_dir(tmp_path):
    write_skill(tmp_path, "deep", OTHER_MD)
    state = tmp_path / "state"
    write_skill(state, "deep")  # same id, different content: first root wins
    (skills,) = discover_skills(tmp_path, state)
    assert skills.id != "Deep Review"


def test_discovery_prunes_junk_dirs(tmp_path):
    write_skill(tmp_path, "py")
    (tmp_path / "skills" / "py" / "node_modules").mkdir(parents=True)
    (tmp_path / "skills" / "py" / "node_modules" / "SKILL.md").write_text(SKILL_MD)
    assert {s.id for s in discover_skills(tmp_path)} == {"py"}


def test_discovery_caps_the_number_of_skills(tmp_path):
    for i in range(MAX_SKILLS + 3):
        write_skill(tmp_path, f"s{i}")
    assert len(discover_skills(tmp_path)) == MAX_SKILLS


# --- front matter ------------------------------------------------------------


def test_parse_front_matter_splits_yaml_from_body():
    data, body = parse_skill_md(SKILL_MD)
    assert data["name"] == "Git Rebasing" and "interactive rebase" in data["description"]
    assert body.startswith("# Git Rebasing") and "force-push" in body


def test_parse_folds_multiline_scalars_into_one_line(tmp_path):
    write_skill(tmp_path, "a", "---\nname: A\ndescription: |\n  line one\n  line two\n---\nBody")
    (skill,) = discover_skills(tmp_path)
    assert skill.description == "line one line two"


@pytest.mark.parametrize(
    "content",
    [
        "no front matter at all",
        "---\nname: A\nnothing but an opener",
        "---\na: [unclosed\n---\nBody",
        "---\n- just a list\n---\nBody",          # YAML parses, but not to a mapping
    ],
)
def test_broken_front_matter_raises_skill_error(content):
    with pytest.raises(SkillError):
        parse_skill_md(content)


@pytest.mark.parametrize(
    "content",
    [
        "---\nname: ''\ndescription: Y\n---\nBody",   # missing name
        "---\nname: A\n---\nBody",                    # missing description
    ],
)
def test_broken_front_matter_makes_a_skill_unusable(tmp_path, content):
    write_skill(tmp_path, "broken", content)
    assert discover_skills(tmp_path) == []


def test_bad_skill_ids_raise(tmp_path):
    write_skill(tmp_path, "has space")
    write_skill(tmp_path, "x" * 65)
    assert discover_skills(tmp_path) == []


def test_overlong_fields_raise(tmp_path):
    write_skill(tmp_path, "big", "---\nname: " + "n" * 121 + "\ndescription: D\n---\nB")
    assert discover_skills(tmp_path) == []


# --- prompt section ----------------------------------------------------------


def test_skills_section_lists_ids_and_descriptions_only():
    from openbot.skills import SkillInfo

    section = skills_section(
        [SkillInfo(id="py", name="Git Rebasing", description="Clean up commit history.", path="p")]
    )
    assert section.startswith("# Skills")
    assert "load_skill" in section
    assert "- py: Clean up commit history." in section
    assert "# Git Rebasing" not in section  # the body never reaches the prompt


def test_skills_section_empty_without_skills():
    assert skills_section([]) == ""


# --- per-bot enablement ------------------------------------------------------


async def test_enabled_skills_filters_by_id_and_name(tmp_path):
    write_skill(tmp_path, "py", SKILL_MD)
    state = tmp_path / ".state"
    write_skill(state, "review", OTHER_MD)
    from openbot.db.models import BotProfile

    settings = FakeSettings(state_dir=state)
    profile = BotProfile(skill_names=["py"])
    assert [s.id for s in enabled_skills(profile, tmp_path, settings)] == ["py"]
    profile = BotProfile(skill_names=["git rebasing"])  # display name, case-insensitive
    assert [s.id for s in enabled_skills(profile, tmp_path, settings)] == ["py"]
    profile = BotProfile(skill_names=["PY"])
    assert [s.id for s in enabled_skills(profile, tmp_path, settings)] == ["py"]
    profile = BotProfile(skill_names=["other-skill"])
    assert enabled_skills(profile, tmp_path, settings) == []
    profile = BotProfile(skill_names=[])
    assert enabled_skills(profile, tmp_path, settings) == []


# --- the load_skill tool -----------------------------------------------------


@pytest_asyncio.fixture
async def _no_actor_runs(services):
    """Stop the actor system so no background run races the assertions."""
    await services.actors.stop()


def rt(services, bot, thread_id):
    ctx = RunContext(
        bot.id, bot.handle, bot.name, thread_id, "run", services.settings.workspace_root, services
    )
    return ToolRuntime(
        context=ctx, store=services.store, state={}, tool_call_id="c", config={},
        stream_writer=lambda *_: None,
    )


async def setup(services, skills_enabled, tool_names=("load_skill",)):
    ws = services.settings.workspace_root
    write_skill(ws, "py")
    write_skill(ws, "review", OTHER_MD)
    sibling(ws, "py", "helper.sh")
    async with services.session_factory() as s:
        eng = bot_actor("eng", tool_names=list(tool_names), skill_names=skills_enabled)
        s.add(eng)
        await s.commit()
        you = await human_actor(s)
        t = await create_thread(services, s, title="t", handles=["eng"], created_by=you)
    return eng, t


async def invoke(services, eng, t, name):
    return await load_skill.ainvoke({"name": name, "runtime": rt(services, eng, t.id)})


async def test_load_skill_returns_body_base_dir_and_sibling_files(services, _no_actor_runs):
    eng, t = await setup(services, ["py"])
    out = await invoke(services, eng, t, "py")
    assert '<skill_content name="Git Rebasing">' in out
    assert "git rebase -i HEAD~3" in out
    assert f"Base directory for this skill: {services.settings.workspace_root / 'skills' / 'py'}" in out
    assert "- helper.sh" in out


async def test_load_skill_matches_by_display_name_case_insensitively(services, _no_actor_runs):
    eng, t = await setup(services, ["review"])
    out = await invoke(services, eng, t, "Deep Review")
    assert '<skill_content name="Deep Review">' in out


async def test_load_skill_lists_no_skills_when_none_enabled(services, _no_actor_runs):
    eng, t = await setup(services, [])
    out = await invoke(services, eng, t, "py")
    assert "no available skill named 'py'" in out and "Available: (none)" in out


async def test_load_skill_does_not_offer_disabled_skills(services, _no_actor_runs):
    eng, t = await setup(services, ["py"])
    out = await invoke(services, eng, t, "review")
    assert "no available skill named 'review'" in out
    assert "Available: py" in out


async def test_load_skill_blank_name_errors(services, _no_actor_runs):
    eng, t = await setup(services, ["py"])
    assert "error:" in await invoke(services, eng, t, "  ")


# --- runner prompt wiring ----------------------------------------------------


async def test_runner_puts_enabled_skills_in_the_system_prompt(settings):
    ScriptedChatModel.seen.clear()  # class-level accumulator shared across tests
    write_skill(settings.workspace_root, "py")
    services, _eng, _t, run = await make(
        settings,
        {"eng": [ai("done")]},
        tool_names=["load_skill"],
        skill_names=["py"],
    )
    await services.runner.execute(run.id)
    system = ScriptedChatModel.seen[0][0]
    assert system.type == "system"
    assert "# Skills" in system.text
    assert "- py: Clean up commit history" in system.text
    assert "git rebase -i" not in system.text  # body loads on demand, not at prompt time


async def test_runner_leaves_skills_out_when_the_bot_has_no_load_skill_tool(settings):
    ScriptedChatModel.seen.clear()  # class-level accumulator shared across tests
    write_skill(settings.workspace_root, "py")
    services, _eng, _t, run = await make(
        settings,
        {"eng": [ai("done")]},
        tool_names=[],
        skill_names=["py"],
    )
    await services.runner.execute(run.id)
    assert "# Skills" not in ScriptedChatModel.seen[0][0].text


# --- sibling file cap --------------------------------------------------------


async def test_render_caps_the_sibling_file_list(tmp_path):
    from openbot.skills import parse_skill
    from openbot.tools.builtin.skills import render_skill_content

    write_skill(tmp_path, "py")
    for i in range(MAX_FILES + 2):
        sibling(tmp_path, "py", f"f{i}.txt", "x")
    out = render_skill_content(parse_skill(tmp_path / "skills" / "py" / "SKILL.md"))
    assert out.count("- f") == MAX_FILES
    assert f"... {MAX_FILES + 2 - MAX_FILES} more" in out


# --- API validation ----------------------------------------------------------


async def test_api_accepts_known_skills_and_rejects_unknown_ones(settings, client):
    write_skill(settings.workspace_root, "py")

    bot = {"handle": "eng", "name": "Eng", "description": "B", "instructions": "Do it",
           "provider": "openai", "model": "m", "tool_names": ["load_skill"], "skill_names": ["py"]}
    r = await client.post("/api/v1/bots", json=bot)
    assert r.status_code == 201, r.text
    assert r.json()["skill_names"] == ["py"]
    r = await client.post("/api/v1/bots", json={**bot, "handle": "x2", "skill_names": ["nope"]})
    assert r.status_code == 422 and "unknown skills" in r.text


async def test_skills_endpoint_lists_discovered_skills(settings, client):
    write_skill(settings.workspace_root, "py")
    r = await client.get("/api/v1/tools/skills")
    assert r.status_code == 200
    (skill,) = r.json()["skills"]
    assert skill["id"] == "py" and "interactive rebase" in skill["description"]
