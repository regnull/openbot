from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from openbot.db.models import Actor, Message


def estimate_tokens(text: str) -> int:
    return len(text) // 4 + 8


def build_history(messages: list[Message], actor_id: str, *, token_budget: int, max_messages: int) -> tuple[list[BaseMessage], int]:
    ordered = sorted(messages, key=lambda m: (m.created_at, m.id))
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
        line = f"[{m.sender_name}]: {m.content}"
        if out and isinstance(out[-1], HumanMessage):
            out[-1] = HumanMessage(content=f"{out[-1].content}\n\n{line}")
        else:
            out.append(HumanMessage(content=line))
    return out, len(ordered) - len(picked)


def build_system_prompt(*, bot: Actor, all_bots: list[Actor], participants: list[str], memories: list[str],
                        workspace_root: str, older_count: int, tool_names: list[str],
                        default_bot_handle: str | None = None) -> str:
    roster = "\n".join(f"- @{b.handle} ({b.name}): {b.description or 'no description'}"
                       for b in all_bots
                       if b.kind == "bot" and b.enabled is not False and b.id != bot.id) or "- (no other bots)"
    mem = "\n".join(f"- {m}" for m in memories) or "- (none yet)"
    older = (f"This thread has {older_count} older messages not shown. Use recall_messages (semantic search) or "
             f"read_history (chronological paging) to fetch them.") if older_count else "The full thread history is shown."
    default_note = (f" The default bot for this thread is @{default_bot_handle}; if the human sends a message without mentioning a bot, that bot is woken."
                    if default_bot_handle else "")
    return f"""You are {bot.name} (@{bot.handle}), a persistent AI bot on the OpenBot platform.
{bot.description}

# Your instructions
{bot.bot.instructions}

# How this platform works
- You are in a shared thread with: {', '.join(participants) or 'nobody else'}. Messages from others appear as "[name]: text". The human operator is @you.
- Your reply is posted to the thread as a message from you. To hand work to another bot or ask it something, mention it with @handle in your reply. Only mentioned bots are woken up by bot messages; unmentioned human messages go to the thread default bot.{default_note} Never mention yourself. Only write @handle when you want that bot to act now. When merely referring to a bot, use its plain name without @.
- To start a separate conversation with bots, use start_thread. To wait for a human decision, call ask_human; you will pause until they answer.
- Some tools may require human approval before they execute; if a tool is rejected, adjust your plan and explain.
- Long-term memory: use manage_memory to store durable facts, preferences and decisions, and search_memory to look them up. Relevant memories are listed below.
- {older}
- The workspace root for shell and file tools is {workspace_root}. Paths are relative to it.
- Tools available to you: {', '.join(tool_names) or 'none besides the built-ins'}.

# Other bots you can mention
{roster}

# Your memories
{mem}
"""
