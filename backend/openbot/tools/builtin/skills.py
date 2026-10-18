"""The load_skill tool: pull a skill's full instructions on demand.

Skills are SKILL.md files under skills/ directories in the workspace or OpenBot's state
directory; their names and descriptions are advertised in the system prompt, and this
tool returns one skill's body -- the instructions -- plus the base directory and the
supporting files that live beside it. The tool is bound only to bots that list it in
their tool_names and have at least one skill enabled (skill_names).

Ported from OpenCode's MIT-licensed skill tool
(anomalyco/opencode@dev, packages/core/src/tool/plugin/skill.ts and skill/index.ts).
"""

from __future__ import annotations

from pathlib import Path

from langchain.tools import ToolRuntime, tool
from sqlalchemy import select

from openbot.db.models import BotProfile
from openbot.skills import SkillError, discover_skills, parse_skill_md
from openbot.tools.builtin.workspace import cap
from openbot.tools.context import RunContext

MAX_FILES = 10


async def enabled_skill_filter(ctx: RunContext) -> set[str]:
    """The ids this bot's operator enabled for it; an empty set means "no skills" """
    async with ctx.services.session_factory() as session:
        row = (await session.execute(
            select(BotProfile.skill_names).where(BotProfile.actor_id == ctx.actor_id)
        )).scalar_one_or_none()
    return set(row or [])


async def available_skills(ctx: RunContext) -> list:
    """The skills this bot may load: discovered (workspace first, then the state dir),
    filtered to the bot's enabled list. A bot with no enabled skills sees none."""
    settings = ctx.services.settings
    roots = [Path(ctx.workspace_root)]
    state_dir = settings.state_dir
    if state_dir is not None and state_dir.resolve() != Path(ctx.workspace_root).resolve():
        roots.append(state_dir)
    skills = discover_skills(*roots)
    enabled = await enabled_skill_filter(ctx)
    if not enabled:
        return []
    lowered = {s.lower() for s in enabled}
    return [s for s in skills if s.id.lower() in lowered or s.name.lower() in lowered]


def render_skill_content(skill) -> str:
    """The loaded skill as the model sees it: body, base directory, sibling files.

    Mirrors OpenCode's <skill_content> envelope; file list capped for prompt hygiene.
    """
    path = Path(skill.path)
    try:
        body = parse_skill_md(path.read_text(encoding="utf-8"))[1]
    except (OSError, SkillError) as exc:
        return f"error: skill {skill.id} is present but unreadable: {exc}"
    files = sorted(p.name for p in path.parent.iterdir() if p.is_file() and p.name != path.name)
    files = files[:MAX_FILES] + ([f"... {len(files) - MAX_FILES} more"] if len(files) > MAX_FILES else [])
    lines = [
        f'<skill_content name="{skill.name}">',
        f"# Skill: {skill.name}",
        "",
        body.strip(),
        "",
        f"Base directory for this skill: {path.parent}",
        "Relative paths in this skill (e.g., scripts/, reference/) are relative to this base directory.",
        "Skill files:",
    ]
    lines += [f"- {name}" for name in files]
    lines.append("</skill_content>")
    return "\n".join(lines)


LOAD_SKILL_DESCRIPTION = """\
Load a skill's full instructions when a task matches that skill's description. Pass the
skill's id from the available-skills list (a case-insensitive name match also works).

Use it before starting work on a matching task: the reply carries the skill's detailed
instructions plus its base directory, so relative paths inside the skill (scripts/,
reference/) resolve -- open those files with read_file when the skill says so. Do not
reload a skill already loaded in this conversation."""


@tool("load_skill", description=LOAD_SKILL_DESCRIPTION)
async def load_skill(name: str, runtime: ToolRuntime[RunContext]) -> str:
    """Load one skill's full instructions by id (or name)."""
    name = (name or "").strip()
    if not name:
        return "error: name must be a skill id from the available-skills list"
    skills = await available_skills(runtime.context)
    lowered = name.lower()
    match = next((s for s in skills if s.id.lower() == lowered or s.name.lower() == lowered), None)
    if match is None:
        ids = ", ".join(sorted(s.id for s in skills))
        return f"error: no available skill named {name!r}. Available: {ids or '(none)'}"
    return cap(render_skill_content(match), runtime.context.tool_output_cap,
               workspace_root=runtime.context.workspace_root)