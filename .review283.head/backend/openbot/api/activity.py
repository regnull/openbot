"""Read side of the activity log (see runtime/activity.py): the timeline for one thread, one bot,
one run, or everything, oldest first."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openbot.api.deps import get_session
from openbot.api.schemas import ActivityOut
from openbot.db.models import ActivityLog

router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("", response_model=list[ActivityOut])
async def list_activity(thread_id: str | None = None, actor_id: str | None = None, run_id: str | None = None,
                        event: str | None = None, level: str | None = None,
                        after_id: int | None = Query(None, description="rows newer than this id (tailing)"),
                        before_id: int | None = Query(None, description="rows older than this id (paging back)"),
                        limit: int = Query(200, ge=1, le=1000), session: AsyncSession = Depends(get_session)):
    """The newest `limit` matching rows (or the `limit` rows after `after_id`), returned oldest first."""
    q = select(ActivityLog)
    for col, val in ((ActivityLog.thread_id, thread_id), (ActivityLog.actor_id, actor_id), (ActivityLog.run_id, run_id),
                     (ActivityLog.event, event), (ActivityLog.level, level)):
        if val is not None:
            q = q.where(col == val)
    if after_id is not None:
        rows = (await session.execute(q.where(ActivityLog.id > after_id).order_by(ActivityLog.id).limit(limit))).scalars().all()
        return list(rows)
    if before_id is not None:
        q = q.where(ActivityLog.id < before_id)
    rows = (await session.execute(q.order_by(ActivityLog.id.desc()).limit(limit))).scalars().all()
    return list(reversed(rows))
