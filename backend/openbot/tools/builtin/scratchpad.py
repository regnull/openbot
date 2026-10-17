"""The scratchpad tool: one per-bot notepad, kept in the database, injected into the system prompt.

The scratchpad is a bot's persistent working memory. It is keyed by bot only — never by thread —
so notes made in one conversation are right there at the start of every run in any other. The
prompt assembler (openbot/runtime/prompt.py) wraps the current content in the `# Your scratchpad`
section (the live, dynamic one — the stable template's static instruction is `# Task scratchpad`)
and appends it to the bot's dynamic system prompt on every run, so the bot sees its notes
without reading anything first.
"""

from __future__ import annotations

from typing import Literal

from langchain.tools import ToolRuntime, tool
from sqlalchemy import select

from openbot.db.models import BotScratchpad
from openbot.tools.context import RunContext

MAX_SCRATCHPAD_CHARS = 4000

SCRATCHPAD_DESCRIPTION = """\
Read and maintain your persistent scratchpad: a per-bot notepad stored server-side. Your current
scratchpad is injected at the start of every run, in every thread, before you read anything —
so anything you save there outlives the conversation's context window, restarts, and even the
thread you saved it in. It is your hand-off to your future self.

## When to use
Write down anything a later run (possibly of a different conversation) will need:
- Task progress: what you are doing, what is done, what is left, where you stopped mid-step.
- Key task information: file paths and line numbers under investigation, branch and PR numbers,
  commands that worked, decisions made and why, open questions, blockers.
- Incremental findings from long investigations, so context-limit summarization cannot eat them.

## Actions
- `read`: return the current scratchpad. Usually unnecessary — it is already in your system
  prompt; read only if you want a clean copy.
- `write`: replaces the ENTIRE scratchpad with `content`. Use it to restructure, prune or start
  fresh. Anything you leave out is deleted.
- `append`: adds `content` to the end of the existing scratchpad. Use it to record new findings
  without disturbing what is already there.

## Rules
- Keep it current: update it as work proceeds (at least after each meaningful step), not only
  at the end. Stale notes mislead your future self.
- Keep it a working outline, not prose: short lines, clearly structured (current state, findings,
  next steps), rather than running narrative of everything you did.
- Prune ruthlessly: the scratchpad is included in every one of your runs, so every dead
  character is a permanent tax on your context. Drop completed steps' details once nothing
  refers to them; keep only what is still actionable or needed for continuity.
- Do not duplicate the todo list (todo_write): use the todo list for task state in this thread,
  and the scratchpad for what you want to carry across threads: knowledge, task info, findings.
- A `write` or `append` that would exceed the size cap is rejected; prune with `write` first.
- The scratchpad is private to you: no other bot sees it, and you cannot see theirs.
"""


def scratchpad_section(content: str) -> str:
    """The saved scratchpad as a prompt section, for the dynamic system prompt.

    Always rendered, even when empty: the stable template tells every bot to keep notes here, and
    an always-present section is how a bot discovers its (still empty) scratchpad exists."""
    if content:
        return f"# Your scratchpad\n{content}"
    return (
        "# Your scratchpad\n(nothing saved yet — use the scratchpad tool to leave notes, "
        "findings and progress for your future runs.)"
    )


async def load_scratchpad(session, actor_id: str) -> str:
    """The bot's saved scratchpad; empty when it has none."""
    row = (
        await session.execute(
            select(BotScratchpad).where(
                BotScratchpad.actor_id == actor_id,
            )
        )
    ).scalar_one_or_none()
    return row.content if row is not None else ""


@tool("scratchpad", description=SCRATCHPAD_DESCRIPTION)
async def scratchpad(
    action: Literal["read", "write", "append"], runtime: ToolRuntime[RunContext], content: str = ""
) -> str:
    ctx = runtime.context
    if action == "read":
        async with ctx.services.session_factory() as session:
            current = await load_scratchpad(session, ctx.actor_id)
        return current or "Scratchpad is empty."
    async with ctx.services.session_factory() as session:
        row = (
            await session.execute(
                select(BotScratchpad).where(
                    BotScratchpad.actor_id == ctx.actor_id,
                )
            )
        ).scalar_one_or_none()
        current = row.content if row is not None else ""
        if action == "write":
            new = content
        else:
            # Appending after a paragraph that does not end in a newline would glue the two
            # together; keep appended blocks intact instead. An empty append adds nothing at all.
            joiner = "\n" if (current and content and not current.endswith("\n")) else ""
            new = f"{current}{joiner}{content}"
        if len(new) > MAX_SCRATCHPAD_CHARS:
            return (
                f"error: the scratchpad is capped at {MAX_SCRATCHPAD_CHARS} characters and this "
                f"{'write' if action == 'write' else 'append'} would make it {len(new)} "
                f"({len(new) - MAX_SCRATCHPAD_CHARS} over). Use action=write with a pruned, "
                "shortened version of your notes, dropping completed work and stale details."
            )
        if row is None:
            session.add(BotScratchpad(actor_id=ctx.actor_id, content=new))
        else:
            row.content = new
        await session.commit()
    length = len(new)
    verb = "replaced" if action == "write" else "appended to"
    return f"Scratchpad {verb} ({length} characters)."
