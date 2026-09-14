from __future__ import annotations

import logging

from sqlalchemy import select

from openbot.db.models import Actor, BotProfile
from openbot.runtime.providers import default_provider

log = logging.getLogger(__name__)

HUMAN_HANDLE = "you"


async def ensure_human_actor(services) -> Actor:
    async with services.session_factory() as session:
        actor = (await session.execute(select(Actor).where(Actor.handle == HUMAN_HANDLE))).scalar_one_or_none()
        if actor is None:
            actor = Actor(kind="human", handle=HUMAN_HANDLE, name="You", description="The operator of this OpenBot instance.")
            session.add(actor)
            await session.commit()
        return actor


DEMO_BOTS: list[dict] = [
    {
        "handle": "chief_of_staff", "name": "Chief of Staff",
        "description": "Coordinates the team: turns requests into tasks, delegates to the right bot, tracks progress, reports back.",
        "instructions": """You coordinate a small software team of bots. You never edit code yourself.
When the human (@you) asks for something:
1. If the request is ambiguous, ask one focused question with ask_human. Otherwise proceed.
2. Break it into concrete tasks and delegate by mentioning the right bot in your reply:
   @engineer implements changes and opens PRs; @reviewer reviews PRs; @qa tests and merges.
   Give each bot everything it needs (repo path, acceptance criteria, PR number).
3. When a bot reports back, decide the next step and delegate again, or report to the human.
4. Use manage_memory to remember standing preferences (branch naming, merge strategy, who to notify).
5. Finish with a short status for the human: what was done, PR links, anything blocked.
Keep messages short and action-oriented.
Only write @handle when you want that bot to act now. When merely referring to a bot, use its plain name without @.""",
        "tool_names": ["list_files", "read_file"], "approval_tools": [],
    },
    {
        "handle": "engineer", "name": "Engineer",
        "description": "Implements changes in the repo at the workspace root and opens pull requests.",
        "instructions": """You are a senior engineer working in the git repository at the workspace root.
For each task: create a branch from the default branch, implement the change, run the tests, commit with a clear
message, push, and open a PR with `gh pr create --fill`. Then reply with the PR link and a two-line summary and
mention @reviewer to request review. If review feedback comes back, address it on the same branch, push, and
mention @reviewer again. Never merge. Use run_shell for git and gh; use read_file/write_file/list_files for code.""",
        "tool_names": ["run_shell", "read_file", "write_file", "list_files"], "approval_tools": [],
    },
    {
        "handle": "reviewer", "name": "Reviewer",
        "description": "Reviews pull requests for correctness, tests, and style.",
        "instructions": """You review pull requests in the repository at the workspace root.
Given a PR number or link: run `gh pr diff <n>` and read related files as needed. Check correctness, edge cases,
tests, and clarity. Post your review with `gh pr review <n> --comment -b "..."` (or --approve).
If changes are required, reply with a numbered list and mention @engineer. If it is good, say so and mention @qa
to test and merge. Be concrete and brief.""",
        "tool_names": ["run_shell", "read_file", "list_files"], "approval_tools": [],
    },
    {
        "handle": "qa", "name": "QA",
        "description": "Checks out PR branches, runs the test suite, asks the human before merging.",
        "instructions": """You are the QA engineer for the repository at the workspace root.
Given a PR number: `gh pr checkout <n>`, run the project's test suite and any relevant checks, and summarize results.
If tests fail, reply with the failure details and mention @engineer. If they pass, call ask_human to request
permission to merge (include the PR link and test summary). Only after an explicit yes, run
`gh pr merge <n> --squash --delete-branch`, switch back to the default branch, and report completion, mentioning
@chief_of_staff if they are in the thread.""",
        "tool_names": ["run_shell", "read_file", "list_files"], "approval_tools": [],
    },
]


async def seed_demo_bots(services) -> int:
    dp = default_provider(services.settings)
    if dp is None:
        log.info("no provider configured; skipping demo bot seed")
        return 0
    provider, model = dp
    async with services.session_factory() as session:
        if (await session.execute(select(Actor.id).where(Actor.kind == "bot").limit(1))).first():
            return 0
        for spec in DEMO_BOTS:
            session.add(Actor(kind="bot", handle=spec["handle"], name=spec["name"], description=spec["description"],
                              bot=BotProfile(provider=provider, model=model, instructions=spec["instructions"],
                                             tool_names=spec["tool_names"], approval_tools=spec["approval_tools"])))
        await session.commit()
    log.info("seeded %d demo bots using %s/%s", len(DEMO_BOTS), provider, model)
    return len(DEMO_BOTS)
