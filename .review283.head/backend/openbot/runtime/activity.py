"""The activity log: a database-side timeline of everything that happens to a thread and a bot.

`logs/openbot.log` already narrates a run; this records the steps *around* the runs, the ones
that decide whether a run happens at all: a message posted and who it was addressed to, the inbox
items it produced, the worker being woken, a worker waiting for a concurrency slot, a worker finding
only mail for a thread that is parked on a question, the run being created, each status change,
the items being settled. When several threads run at once and one of them stops progressing, the
rows for that thread and that bot (`GET /api/v1/activity?thread_id=...`, `?actor_id=...`) say where it
stalled, without reproducing anything.

`record` never raises: the log is diagnostics, and a failure to write it must never break the thing
it describes. It writes with its own short session unless the caller passes `session`, which makes
the row part of the caller's transaction (required when the caller holds uncommitted writes: a
second SQLite connection would block on the first one's lock).
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from openbot.db.models import ActivityLog, utcnow

log = logging.getLogger(__name__)
PREVIEW_CAP = 300

# Every event name, so a typo in a call site fails the test that exercises it instead of producing a
# row nobody filters for.
EVENTS = frozenset({
    "system.started",
    "recovery.run_failed", "recovery.items_requeued",
    "thread.created",
    "message.posted", "message.hop_limit", "message.handoff_held",
    "inbox.enqueued", "inbox.picked", "inbox.settled", "inbox.acked", "inbox.purged", "inbox.hold_released",
    "question.delivered",
    "resume.picked",
    "worker.notified", "worker.drain.start", "worker.drain.end", "worker.error",
    "worker.slot.wait", "worker.slot.acquired", "worker.parked",
    "run.created", "run.dispatched", "run.started", "run.status", "run.finished", "run.cancel_requested",
    "run.model_call", "run.tool_call", "run.tool_result", "run.interrupt",
    "webhook.attempt",
})
LEVELS = ("debug", "info", "warning", "error")


def preview(value: Any, cap: int = PREVIEW_CAP) -> str:
    """Single-line, size-capped rendering for the `detail` column: enough to recognise a message or a
    tool call, never a full file body."""
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    text = text.replace("\n", "\\n")
    return text if len(text) <= cap else text[:cap] + f"... [{len(text) - cap} more chars]"


async def record(services, event: str, *, summary: str, level: str = "info", thread_id: str | None = None,
                 actor_id: str | None = None, run_id: str | None = None, item_id: str | None = None,
                 message_id: str | None = None, session: AsyncSession | None = None, **detail: Any) -> ActivityLog | None:
    """Append one row. Returns the row, or None if it could not be written (already logged)."""
    if event not in EVENTS:
        raise ValueError(f"unknown activity event: {event!r}")
    if level not in LEVELS:
        raise ValueError(f"unknown activity level: {level!r}")
    row = ActivityLog(event=event, summary=summary, level=level, thread_id=thread_id, actor_id=actor_id, run_id=run_id,
                      item_id=item_id, message_id=message_id, detail=detail, created_at=utcnow())
    # Mirror into the file log at DEBUG so the two timelines can be lined up; the console already gets
    # the runner's own INFO lines and must not see everything twice.
    log.debug("%s thread=%s actor=%s run=%s item=%s: %s %s", event, thread_id, actor_id, run_id, item_id, summary,
              preview(detail) if detail else "")
    try:
        if session is not None:
            session.add(row)
            return row
        async with services.session_factory() as s:
            s.add(row)
            await s.commit()
        return row
    except Exception:
        log.exception("could not record activity %s (%s)", event, summary)
        return None


async def prune(services, days: int) -> int:
    """Delete rows older than `days`; 0 or less keeps everything. Returns the number deleted."""
    if days <= 0:
        return 0
    cutoff = utcnow() - timedelta(days=days)
    try:
        async with services.session_factory() as s:
            res = await s.execute(delete(ActivityLog).where(ActivityLog.created_at < cutoff))
            await s.commit()
        n = int(res.rowcount or 0)
        if n:
            log.info("activity log: pruned %d rows older than %d days", n, days)
        return n
    except Exception:
        log.exception("could not prune the activity log")
        return 0
