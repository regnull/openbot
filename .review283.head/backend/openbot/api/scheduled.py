from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from openbot.api.deps import get_services, get_session
from openbot.db.models import Actor, ScheduledMessage, Thread, ThreadParticipant, utcnow
from openbot.services import Services

router = APIRouter(prefix="/scheduled", tags=["scheduled"])


async def scheduled_actor(actor_handle: str | None = Header(default=None, alias="X-OpenBot-Actor"),
                          session=Depends(get_session)) -> Actor:
    """Resolve the explicit operator identity; never infer an actor."""
    if not actor_handle:
        raise HTTPException(401, "X-OpenBot-Actor is required for scheduled messages")
    actor = (await session.execute(select(Actor).where(Actor.handle == actor_handle))).scalar_one_or_none()
    if actor is None or not actor.enabled:
        raise HTTPException(403, "unknown or disabled actor")
    return actor


class Create(BaseModel):
    thread_id: str
    content: str = Field(min_length=1, max_length=20_000)
    due_at: datetime
    to: list[str] = Field(default_factory=list, max_length=20)


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    thread_id: str
    content: str
    due_at: datetime
    status: str
    attempts: int
    last_error: str | None
    result_message_id: str | None
    to_handles: list[str]


async def _validate_target(session, thread_id: str, handles: list[str]) -> None:
    thread = await session.get(Thread, thread_id)
    if thread is None:
        raise HTTPException(404, "thread not found")
    actors = {a.handle: a for a in (await session.execute(select(Actor))).scalars()}
    unknown = [h for h in handles if h not in actors or actors[h].kind != "bot" or not actors[h].enabled]
    if unknown:
        raise HTTPException(422, f"unknown or unavailable bot handles: {unknown}")
    participant_ids = set((await session.execute(
        select(ThreadParticipant.actor_id).where(ThreadParticipant.thread_id == thread_id)
    )).scalars())
    not_in_thread = [h for h in handles if actors[h].id not in participant_ids]
    if not_in_thread:
        raise HTTPException(422, f"recipients are not participants in the target thread: {not_in_thread}")


async def _owned(session, job_id: str, actor: Actor) -> ScheduledMessage:
    job = (await session.execute(select(ScheduledMessage).where(
        ScheduledMessage.id == job_id, ScheduledMessage.sender_actor_id == actor.id
    ))).scalar_one_or_none()
    if job is None:
        raise HTTPException(404, "scheduled message not found")
    return job


@router.get("", response_model=list[Out])
async def list_scheduled(actor: Actor = Depends(scheduled_actor), session=Depends(get_session)):
    return (await session.execute(select(ScheduledMessage).where(
        ScheduledMessage.sender_actor_id == actor.id
    ).order_by(ScheduledMessage.due_at.desc()).limit(200))).scalars().all()


@router.get("/{job_id}", response_model=Out)
async def inspect(job_id: str, actor: Actor = Depends(scheduled_actor), session=Depends(get_session)):
    return await _owned(session, job_id, actor)


@router.post("", response_model=Out, status_code=201)
async def create(body: Create, actor: Actor = Depends(scheduled_actor), session=Depends(get_session),
                 services: Services = Depends(get_services)):
    due = body.due_at.astimezone(UTC) if body.due_at.tzinfo else body.due_at.replace(tzinfo=UTC)
    if due <= utcnow():
        raise HTTPException(422, "due_at must be in the future")
    await _validate_target(session, body.thread_id, body.to)
    participant = await session.scalar(select(ThreadParticipant.actor_id).where(
        ThreadParticipant.thread_id == body.thread_id, ThreadParticipant.actor_id == actor.id
    ))
    if participant is None:
        raise HTTPException(403, "actor is not a participant in the target thread")
    job = ScheduledMessage(thread_id=body.thread_id, sender_actor_id=actor.id, to_handles=body.to,
                           content=body.content, due_at=due)
    session.add(job)
    await session.commit()
    await session.refresh(job)
    await services.bus.publish("scheduled.updated", body.thread_id, {"id": job.id, "status": job.status})
    return job


@router.post("/{job_id}/cancel", response_model=Out)
async def cancel(job_id: str, actor: Actor = Depends(scheduled_actor), session=Depends(get_session),
                 services: Services = Depends(get_services)):
    job = await _owned(session, job_id, actor)
    if job.status == "pending":
        job.status = "cancelled"
        await session.commit()
        await services.bus.publish("scheduled.updated", job.thread_id, {"id": job.id, "status": job.status})
        await session.refresh(job)
    return job
