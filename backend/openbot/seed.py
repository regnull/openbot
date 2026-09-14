from __future__ import annotations

from sqlalchemy import select

from openbot.db.models import Actor

HUMAN_HANDLE = "you"


async def ensure_human_actor(services) -> Actor:
    async with services.session_factory() as session:
        actor = (await session.execute(select(Actor).where(Actor.handle == HUMAN_HANDLE))).scalar_one_or_none()
        if actor is None:
            actor = Actor(kind="human", handle=HUMAN_HANDLE, name="You", description="The operator of this OpenBot instance.")
            session.add(actor)
            await session.commit()
        return actor
