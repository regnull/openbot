from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from openbot.api import actors, bots, events, providers, tools
from openbot.api.deps import require_api_key
from openbot.config import Settings, get_settings
from openbot.db.session import create_all, make_engine, make_session_factory, run_migrations
from openbot.runtime.bus import EventBus
from openbot.runtime.persistence import open_langgraph_backends
from openbot.runtime.providers import chat_model, embeddings
from openbot.seed import ensure_human_actor
from openbot.services import Services
from openbot.tools.registry import build_registry


async def build_services(settings: Settings) -> Services:
    if ":memory:" in settings.database_url:
        engine = make_engine(settings.database_url)
        await create_all(engine)
    else:
        await run_migrations(settings.database_url)
        engine = make_engine(settings.database_url)
    services = Services(settings=settings, session_factory=make_session_factory(engine))
    services.registry = build_registry(settings)
    services.bus = EventBus()
    services.model_factory = lambda actor: chat_model(actor.bot, settings)

    stack = AsyncExitStack()
    emb = embeddings(settings)
    services.checkpointer, services.store = await stack.enter_async_context(
        open_langgraph_backends(settings, emb)
    )
    services._owned_resources = [engine, stack]
    return services


async def close_services(services: Services) -> None:
    for r in services._owned_resources:
        if isinstance(r, AsyncExitStack):
            await r.aclose()
        else:
            await r.dispose()


async def start_background(services: Services) -> None:
    await ensure_human_actor(services)


async def stop_background(services: Services) -> None:
    return None


def create_app(settings: Settings | None = None, services: Services | None = None) -> FastAPI:
    load_dotenv()
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        owned = app.state.services is None
        if owned:
            app.state.services = await build_services(settings)
        await start_background(app.state.services)
        try:
            yield
        finally:
            await stop_background(app.state.services)
            if owned:
                await close_services(app.state.services)

    app = FastAPI(title="OpenBot", lifespan=lifespan)
    app.state.settings = settings
    app.state.services = services
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

    public = APIRouter(prefix="/api/v1")

    @public.get("/health")
    async def health():
        return {"status": "ok"}

    api = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])
    api.include_router(actors.router)
    api.include_router(bots.router)
    api.include_router(tools.router)
    api.include_router(events.router)
    api.include_router(providers.router)
    app.include_router(public)
    app.include_router(api)
    return app


app = create_app()
