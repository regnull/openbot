"""Skill discovery: SKILL.md files under skills/ directories, loaded on demand.

A skill is a markdown file with YAML front matter giving at least a name (a short
identifier) and a one-line description. Skills live in `skills/**/SKILL.md` under the
workspace root, or `skills/<id>.md` files directly inside a skills directory, and are
sourced from two roots: the workspace and OpenBot's own state directory (`.openbot`),
where an operator can drop skills without touching the repository. Only the identifiers
and descriptions enter the system prompt (via `skills_section`); the `load_skill` tool
fetches a skill's full body on demand.

Ported from OpenCode's MIT-licensed skill support
(anomalyco/opencode@dev, packages/core/src/skill/instructions.ts and
config/plugin/skill-file.ts).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from openbot.db.models import BotProfile

SKILL_FILE = "SKILL.md"
# Prompt budget guard: skills are advertised in every run's system prompt for bots that
# enable them, so an accidental skills/ monstrerosity should not grow every prompt.
MAX_SKILLS = 64
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".openbot"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$", re.IGNORECASE)
MAX_ID_CHARS = 64


@dataclass(frozen=True)
class SkillInfo:
    id: str
    name: str
    description: str
    path: str


class SkillError(ValueError):
    """A SKILL.md exists but is not a usable skill (bad front matter, bad id)."""


def parse_skill_md(content: str) -> tuple[dict, str]:
    """Split front matter from body; returns ({...front matter...}, body).

    Raises SkillError when the front matter delimiters or YAML are malformed.
    """
    if not content.startswith("---"):
        raise SkillError("missing front matter: the file must start with a `---` line")
    end = content.find("\n---", 3)
    if end < 0:
        raise SkillError("unterminated front matter: missing the closing `---` line")
    try:
        data = yaml.safe_load(content[3:end]) or {}
    except yaml.YAMLError as exc:
        raise SkillError(f"invalid front matter YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise SkillError("front matter must be a YAML mapping")
    return data, content[end + 4:].lstrip("\n")


def _clean(value) -> str:
    """Fold a YAML scalar (maybe a multiline block, maybe None) into one clean line."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def parse_skill(path: Path) -> SkillInfo:
    """Parse one SKILL.md-ish file into a SkillInfo, validating id, name, description."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SkillError(f"unreadable skill file {path}: {exc}") from exc
    data, _body = parse_skill_md(content)
    name = _clean(data.get("name"))
    description = _clean(data.get("description"))
    # SKILL.md files take their id from their directory (skills/<id>/SKILL.md); a
    # skills/<id>.md top-level file is its own id (OpenCode's dual layout).
    ident = path.stem if path.name != SKILL_FILE else path.parent.name
    ident = _clean(ident)
    if not ident or len(ident) > MAX_ID_CHARS or not ID_RE.match(ident):
        raise SkillError(f"invalid skill id {ident!r} in {path}")
    if not name:
        raise SkillError(f"missing `name` in front matter of {path}")
    if not description:
        raise SkillError(f"missing `description` in front matter of {path}")
    if len(name) > 120 or len(description) > 1024:
        raise SkillError(f"`name`/`description` too long in front matter of {path}")
    return SkillInfo(id=ident, name=name, description=description, path=str(path))


def discover_skills(*roots: Path) -> list[SkillInfo]:
    """Find skills under each root's skills/ directories, deduped by id (first root wins).

    The earlier roots shadow the later ones, so workspace skills override skill ids of
    the same name from the state directory. `skills/<id>/SKILL.md` takes its id from its
    directory; `skills/<id>.md` standing directly in a skills directory names itself.
    Unparseable files are skipped: one broken skill must not break the rest.
    """
    seen: dict[str, SkillInfo] = {}
    for root in roots:
        skills_dir = Path(root) / "skills"
        if not skills_dir.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(skills_dir):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for filename in filenames:
                path = Path(dirpath) / filename
                depth = len(path.relative_to(skills_dir).parts)
                nested = depth > 1
                if nested and path.suffix != ".md":
                    continue  # supporting files live next to the skill, they are not skills
                if not nested and path.name != SKILL_FILE and path.suffix != ".md":
                    continue
                try:
                    skill = parse_skill(path)
                except (SkillError, OSError):
                    continue
                seen.setdefault(skill.id, skill)
                if len(seen) >= MAX_SKILLS:
                    return list(seen.values())
    return list(seen.values())


def skills_section(skills: list[SkillInfo]) -> str:
    """The prompt section advertising available skills; empty when there are none.

    Only ids, names and descriptions go here — bodies arrive via the load_skill tool.
    """
    if not skills:
        return ""
    lines = [
        "# Skills",
        "Skills provide specialized instructions and workflows for specific tasks. When a task",
        "matches one of these descriptions, call load_skill with the skill's id to read its",
        "instructions before starting work.",
    ]
    for skill in skills:
        lines.append(f"- {skill.id}: {skill.description}")
    return "\n".join(lines)


def enabled_skills(bot: BotProfile, workspace_root: Path | str | None, settings) -> list[SkillInfo]:
    """Discover the skills this bot has enabled, in prompt order.

    Skips discovery entirely for bots with no skills enabled, so an empty skill list
    costs nothing at run time.
    """
    enabled = {s.lower() for s in (bot.skill_names or [])}
    if not enabled:
        return []
    roots = []
    if workspace_root:
        roots.append(Path(workspace_root))
    state_dir = getattr(settings, "state_dir", None)
    if state_dir and str(Path(state_dir)) != str(workspace_root):
        roots.append(Path(state_dir))
    if not roots:
        return []
    return [
        skill
        for skill in discover_skills(*roots)
        if skill.id.lower() in enabled or skill.name.lower() in enabled
    ]