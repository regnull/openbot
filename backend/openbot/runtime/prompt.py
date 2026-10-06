from __future__ import annotations

from pathlib import Path
from string import Template

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from openbot.db.models import Actor, Message

SYSTEM_PROMPT_FILE = Path(__file__).with_name("system_prompt.md")
_SYSTEM_PROMPT_FIELDS = frozenset({
    "bot_name", "bot_handle", "bot_description", "bot_instructions", "lead_context", "participants",
    "default_note", "lead_note", "lead_instructions", "older", "workspace_root", "tool_names", "roster", "mem",
})


def estimate_tokens(text: str) -> int:
    return len(text) // 4 + 8


def _load_system_prompt_template() -> str:
    try:
        template = SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Unable to load shared system prompt from {SYSTEM_PROMPT_FILE}") from exc
    try:
        actual_fields = frozenset(Template(template).get_identifiers())
    except ValueError as exc:
        raise RuntimeError(f"Invalid shared system prompt {SYSTEM_PROMPT_FILE}: {exc}") from exc
    if actual_fields != _SYSTEM_PROMPT_FIELDS:
        missing = sorted(_SYSTEM_PROMPT_FIELDS - actual_fields)
        unexpected = sorted(actual_fields - _SYSTEM_PROMPT_FIELDS)
        details = []
        if missing:
            details.append(f"missing placeholders: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected placeholders: {', '.join(unexpected)}")
        raise RuntimeError(f"Invalid shared system prompt {SYSTEM_PROMPT_FILE}: {'; '.join(details)}")
    return template


# Read once at import, so the template always matches the code that fills it. Bots edit OpenBot's own
# source in the workspace; re-reading the file per run let a half-applied edit (a new placeholder the
# running code doesn't fill) fail every run until restart.
_SYSTEM_PROMPT_TEMPLATE = Template(_load_system_prompt_template())


def build_history(messages: list[Message], actor_id: str, *, token_budget: int, max_messages: int,
                  trigger_ids: set[str] | frozenset[str] = frozenset()) -> tuple[list[BaseMessage], int]:
    """Render the thread from the bot's point of view. Messages in `trigger_ids` (the ones that woke
    this run) are marked "(new)" so the model knows what it is answering; other bots may have posted
    since its last reply, and several triggers may have been coalesced into one run. A trigger that
    arrived before the bot's own latest reply was queued while the bot was mid-run and may already be
    answered by that reply; it is marked as such so the model checks instead of redoing the work."""
    ordered = sorted(messages, key=lambda m: (m.created_at, m.id))
    own = [m for m in ordered if m.sender_kind == "bot" and m.sender_actor_id == actor_id]
    last_own = (own[-1].created_at, own[-1].id) if own else None
    picked: list[Message] = []
    used = 0
    for m in reversed(ordered):
        cost = estimate_tokens(m.content)
        if picked and (len(picked) >= max_messages or used + cost > token_budget):
            break
        picked.append(m)
        used += cost
    picked.reverse()
    out: list[BaseMessage] = []
    for m in picked:
        if m.sender_kind == "bot" and m.sender_actor_id == actor_id:
            # Otherwise the model takes its cut-off reply for a finished one.
            interrupted = (getattr(m, "meta", None) or {}).get("interrupted")
            out.append(AIMessage(content=f"{m.content}\n\n[interrupted by the user]".lstrip() if interrupted else m.content))
            continue
        tag = ""
        if m.id in trigger_ids:
            stale = last_own is not None and (m.created_at, m.id) < last_own
            tag = " (new, arrived before your last reply; it may already be handled)" if stale else " (new)"
        n_imgs = len((getattr(m, "meta", None) or {}).get("attachments") or [])
        if n_imgs:
            tag += f" [attached {n_imgs} image{'s' if n_imgs > 1 else ''}]"
        line = f"[{m.sender_name}]{tag}: {m.content}"
        if out and isinstance(out[-1], HumanMessage):
            out[-1] = HumanMessage(content=f"{out[-1].content}\n\n{line}")
        else:
            out.append(HumanMessage(content=line))
    return out, len(ordered) - len(picked)


def build_system_prompt(*, bot: Actor, all_bots: list[Actor], participants: list[str], memories: list[str],
                        workspace_root: str, older_count: int, tool_names: list[str],
                        default_bot_handle: str | None = None, scoped: bool = False) -> str:
    """`scoped` is the view a delegate gets: only the messages addressed to it and its own replies, with
    `older_count` other messages hidden. The default bot (or the only bot in a thread) sees the whole
    thread, and `older_count` is then what fell outside the history budget."""
    roster = "\n".join(f"- @{b.handle} ({b.name}): {b.description or 'no description'}"
                       for b in all_bots
                       if b.kind == "bot" and b.enabled is not False and b.id != bot.id) or "- (no other bots)"
    mem = "\n".join(f"- {m}" for m in memories) or "- (none yet)"
    if scoped:
        older = (f"You see only the messages addressed to you (@{bot.handle}) and your own earlier replies in this thread; "
                 f"{older_count} other messages exist but are not shown. The message that woke you should contain everything "
                 f"you need. If it does not, use read_history (chronological, by message id) or recall_messages (semantic "
                 f"search) to fetch the rest before asking a human.")
    else:
        older = (f"This thread has {older_count} older messages not shown. Use recall_messages (semantic search) or "
                 f"read_history (chronological paging) to fetch them.") if older_count else "The full thread history is shown."
    default_note = (f" The default bot for this thread is @{default_bot_handle}; if the human sends a message without mentioning a bot, that bot is woken."
                    if default_bot_handle else "")
    lead_note = f" (@{default_bot_handle})" if default_bot_handle else ""
    lead_context = (f"- thread lead for this thread is @{default_bot_handle}. If you are not sure about the handoff, do a handoff to the thread lead.\n"
                    if default_bot_handle else "")
    lead_instructions = ("- you are the lead for this thread. When human talks to you, follow this process: 1. Understand the request. If it's a simple question, answer it. 2. If it's a task request, plan the task execution. 3. Your plan must include which bots will be called, and in which order. 4. Call the next bot with comprehensive instructions. 5. When a bot does a handoff to you, understand where you are in task execution, and either handoff to the next bot, or reply to human. 6. When the task is complete, reply to human.\n"
                         if default_bot_handle and bot.handle == default_bot_handle else "")
    return _SYSTEM_PROMPT_TEMPLATE.substitute(
        bot_name=bot.name, bot_handle=bot.handle, bot_description=bot.description,
        bot_instructions=bot.bot.instructions, lead_context=lead_context,
        participants=', '.join(participants) or 'nobody else', default_note=default_note,
        lead_note=lead_note, lead_instructions=lead_instructions, older=older,
        workspace_root=workspace_root, tool_names=', '.join(tool_names) or 'none besides the built-ins',
        roster=roster, mem=mem,
    )
