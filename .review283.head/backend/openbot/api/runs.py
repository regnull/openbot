from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openbot.api.deps import get_services, get_session
from openbot.api.schemas import ResumeBody, RunDetail, RunEventOut, RunOut
from openbot.db.models import InboxItem, Run, RunEvent
from openbot.runtime.delivery import ack_items, human_actor
from openbot.services import Services

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=list[RunOut])
async def list_runs(thread_id: str | None = None, session: AsyncSession = Depends(get_session)):
    q = select(Run).order_by(Run.created_at.desc()).limit(200)
    if thread_id:
        q = q.where(Run.thread_id == thread_id)
    return (await session.execute(q)).scalars().all()


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(run_id: str, session: AsyncSession = Depends(get_session)):
    run = await session.get(Run, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    events = (await session.execute(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq))).scalars().all()
    d = RunDetail.model_validate(run)
    d.events = [RunEventOut.model_validate(e) for e in events]
    return d


@router.post("/{run_id}/resume", response_model=RunOut)
async def resume_run(run_id: str, body: ResumeBody, session: AsyncSession = Depends(get_session),
                     services: Services = Depends(get_services)):
    run = await session.get(Run, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    if run.status != "waiting_human" or not run.interrupt:
        raise HTTPException(409, "run is not waiting for human input")
    if run.interrupt.get("kind") == "question":
        if body.answer is None:
            raise HTTPException(422, "answer is required for a question")
        value = body.answer
    else:
        n = len(run.interrupt.get("actions", []))
        if not body.decisions or len(body.decisions) != n:
            raise HTTPException(422, f"decisions must have exactly {n} entries")
        value = {"decisions": [{"type": d} for d in body.decisions]}
    questions = list((await session.execute(select(InboxItem).where(InboxItem.run_id == run_id, InboxItem.kind == "question",
                                                                   InboxItem.status == "queued"))).scalars().all())
    await ack_items(services, session, questions)
    you = await human_actor(session)
    await services.actors.enqueue_resume(run, value, you)
    return run


@router.post("/{run_id}/cancel", response_model=RunOut)
async def cancel_run(run_id: str, session: AsyncSession = Depends(get_session), services: Services = Depends(get_services)):
    run = await session.get(Run, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    if not await services.actors.cancel_run(run_id):
        raise HTTPException(409, "run is not cancellable")
    await session.refresh(run)
    return run
