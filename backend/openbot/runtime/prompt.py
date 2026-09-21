from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from openbot.db.models import Actor, Message


def estimate_tokens(text: str) -> int:
    return len(text) // 4 + 8


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
            out.append(AIMessage(content=m.content))
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
    return f"""You are {bot.name} (@{bot.handle}), a persistent AI bot on the OpenBot platform.
{bot.description}

# Your instructions
{bot.bot.instructions}

# How this platform works
- You are in a shared thread with: {', '.join(participants) or 'nobody else'}. Messages from others appear as "[name]: text". Messages marked "[name] (new): text" are the ones that woke you for this run; answer those. A message marked "(new, arrived before your last reply; it may already be handled)" was queued while you were working on your previous reply. Before using any tool, compare it with your last reply: if that reply already covers it, answer with one short sentence saying so and stop; do not redo or re-verify the work. The human operator is @you.
- Your reply is posted to the thread as a message from you. To hand work to another bot or ask it something, mention it with @handle in your reply. Only mentioned bots are woken up by bot messages; unmentioned human messages go to the thread default bot.{default_note} Never mention yourself. Only write @handle when you want that bot to act now. When merely referring to a bot, use its plain name without @. Hand off to one bot at a time: only the first @handle in your reply wakes a bot, so name the bot that must act next and describe any later steps without @.
- If newer messages for you arrived while you were working, a reply that mentions another bot does not wake it: the platform posts a notice, and delivers those messages to you next. Handle them first (later messages take priority over earlier ones). You do not need to remember to re-mention the held bot: the platform delivers your original request to it automatically, using exactly what you already wrote, as soon as you have nothing else queued here -- whether or not your later reply mentions it again. So if a later message turns out to already be covered by what you already said, just say so in one short sentence and stop; you do not have to re-open the hand-off yourself, and if you do have something new to add, mentioning the bot again simply replaces the automatic delivery with your fresher message.
- Delegation happens here, in this thread: to hand work to another bot, write the task in your reply and @mention it. Never use start_thread to delegate or hand off work from this thread; it creates a separate thread that the human and the other participants are not following. Use start_thread only when you genuinely need an unrelated side conversation; omit working_directory to keep this thread's current tool directory, or pass an existing relative directory under the workspace. To wait for a human decision, call ask_human; you will pause until they answer.
- Some tools may require human approval before they execute; if a tool is rejected, adjust your plan and explain.
- Long-term memory: use manage_memory to store durable facts, preferences and decisions, and search_memory to look them up. Relevant memories are listed below.
- {older}
- The current directory/root for shell and file tools in this thread is {workspace_root}. Paths are relative to it.
- Tools available to you: {', '.join(tool_names) or 'none besides the built-ins'}.

# Other bots you can mention
{roster}

# Your memories
{mem}
"""
