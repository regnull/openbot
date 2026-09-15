from __future__ import annotations

import re

from openbot.db.models import Actor

MENTION_RE = re.compile(r"(?<![\w@.])@([a-z0-9_-]{2,32})(?![\w-])(?!\.\w)")


def parse_mentions(content: str) -> list[str]:
    seen: list[str] = []
    for m in MENTION_RE.finditer(content):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def resolve_targets(*, sender: Actor | None, mentioned_handles: list[str], to_handles: list[str],
                    actors_by_handle: dict[str, Actor], thread_bot_ids: list[str],
                    default_bot_id: str | None = None) -> list[Actor]:
    if sender is None:
        return []
    ordered: list[Actor] = []
    for h in [*to_handles, *mentioned_handles]:
        a = actors_by_handle.get(h)
        if a and a.kind == "bot" and a not in ordered:
            ordered.append(a)
    if not ordered and not (to_handles or mentioned_handles):
        if sender.kind == "human" and default_bot_id is not None:
            ordered = [a for a in actors_by_handle.values() if a.id == default_bot_id and a.kind == "bot"]
        elif len(thread_bot_ids) == 1:
            ordered = [a for a in actors_by_handle.values() if a.id == thread_bot_ids[0] and a.kind == "bot"]
    return [a for a in ordered if a.enabled and a.id != sender.id]
