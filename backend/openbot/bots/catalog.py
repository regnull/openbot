"""Validated metadata for repository-backed, opt-in bot profiles."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

INSTRUCTIONS_DIR = Path(__file__).with_name("instructions")


class BotCatalogEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    handle: str = Field(pattern=r"^[a-z0-9_-]{2,32}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1)
    icon: str = Field(min_length=1)
    instruction_file: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*\.md$")
    tool_names: tuple[str, ...] = ()
    approval_tools: tuple[str, ...] = ()
    model_settings: dict = {}
    load_repository_instructions: bool = False


CATALOG: tuple[dict, ...] = (
    {
        "id": "chief_of_staff",
        "handle": "chief_of_staff",
        "name": "Chief of Staff",
        "description": "Coordinates the team: turns requests into tasks, delegates to the right bot, tracks progress, reports back.",
        "icon": "crown",
        "instruction_file": "chief_of_staff.md",
        "tool_names": (
            "create_bot",
            "read_bot_description",
            "read_bot_instructions",
            "update_bot_description",
            "update_bot_instructions",
        ),
        "model_settings": {"max_model_calls": 6},
    },
    {
        "id": "engineer",
        "handle": "engineer",
        "name": "Engineer",
        "description": "Implements changes in the repo at the workspace root and opens pull requests.",
        "icon": "wrench",
        "instruction_file": "engineer.md",
        "tool_names": ("run_shell", "read_file", "write_file", "list_files", "search_code"),
        "load_repository_instructions": True,
    },
    {
        "id": "reviewer",
        "handle": "reviewer",
        "name": "Reviewer",
        "description": "Reviews pull requests for correctness, tests, and style.",
        "icon": "magnifier",
        "instruction_file": "reviewer.md",
        "tool_names": ("run_shell", "read_file", "list_files", "search_code"),
    },
    {
        "id": "qa",
        "handle": "qa",
        "name": "QA",
        "description": "Checks out PR branches, runs the test suite, asks the human before merging.",
        "icon": "shield",
        "instruction_file": "qa.md",
        "tool_names": ("run_shell", "read_file", "list_files", "search_code"),
    },
    {
        "id": "frontend_designer",
        "handle": "frontend_designer",
        "name": "Frontend Designer",
        "description": "Creates cohesive, accessible frontend direction and implementation-ready UI guidance.",
        "icon": "palette",
        "instruction_file": "frontend_designer.md",
        "tool_names": ("run_shell", "read_file", "list_files", "search_code"),
    },
)

CATALOG_BY_ID = {entry["id"]: entry for entry in CATALOG}


def load_instructions(entry: BotCatalogEntry | dict) -> str:
    """Load an instruction file only after catalog metadata has been validated."""
    item = entry if isinstance(entry, BotCatalogEntry) else BotCatalogEntry.model_validate(entry)
    path = (INSTRUCTIONS_DIR / item.instruction_file).resolve()
    if path.parent != INSTRUCTIONS_DIR.resolve() or not path.is_file():
        raise ValueError(f"missing bot catalog instruction file: {item.instruction_file}")
    return path.read_text(encoding="utf-8").strip()


for _entry in CATALOG:
    _validated = BotCatalogEntry.model_validate(_entry)
    if not load_instructions(_validated):
        raise ValueError(f"empty bot catalog instruction file: {_validated.instruction_file}")
