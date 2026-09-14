from __future__ import annotations

import logging
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from openbot.api import actors, bots, events, inbox, messages, providers, runs, threads, tools
from openbot.api.deps import require_api_key
from openbot.config import Settings, get_settings
from openbot.db.session import create_all, make_engine, make_session_factory, run_migrations
from openbot.runtime.actors import ActorSystem
from openbot.runtime.bus import EventBus
from openbot.runtime.memory import MemoryReflector
from openbot.runtime.persistence import open_langgraph_backends
from openbot.runtime.providers import chat_model, embeddings
from openbot.runtime.runner import Runner
from openbot.seed import ensure_human_actor, seed_demo_bots
from openbot.services import Services
from openbot.tools.registry import build_registry

log = logging.getLogger(__name__)


async def build_services(settings: Settings) -> Services:
    if ":memory:" in settings.database_url:
        engine = make_engine(settings.database_url)
        await create_all(engine)
    else:
        await run_migrations(settings.database_url)
        engine = make_engine(settings.database_url)
    services = Services(settings=settings, session_factory=make_session_factory(engine))
    stack = AsyncExitStack()
    services.registry = build_registry(settings)
    services.bus = EventBus()
    emb = embeddings(settings)
    if emb is None:
        log.warning("no embedding provider configured; memory search will not be semantic")
    services.checkpointer, services.store = await stack.enter_async_context(open_langgraph_backends(settings, emb))
    services.model_factory = lambda actor: chat_model(actor.bot, settings)
    services.reflector = MemoryReflector(services, settings.memory_reflection_delay)
    services.runner = Runner(services)
    services.http_client = httpx.AsyncClient(timeout=15)
    services.actors = ActorSystem(services, settings.max_concurrent_runs)
    services._owned_resources = [engine, stack, services.http_client]
    Path(settings.workspace_root).mkdir(parents=True, exist_ok=True)
    return services


async def close_services(services: Services) -> None:
    for r in services._owned_resources:
        if isinstance(r, AsyncExitStack | httpx.AsyncClient):
            await r.aclose()
        else:
            await r.dispose()


async def start_background(services: Services) -> None:
    await ensure_human_actor(services)
    if services.settings.seed_demo_bots:
        await seed_demo_bots(services)
    if services.actors is not None:
        await services.actors.start()


async def stop_background(services: Services) -> None:
    if services.actors is not None:
        await services.actors.stop()
    if services.reflector is not None:
        await services.reflector.shutdown()


def _configure_logging() -> None:
    """uvicorn configures only its own loggers, so openbot's own INFO lines (demo bot seeding, the
    missing-embedding-provider warning) never reach the console. Attach one handler to the openbot
    logger — scoped, and only once, so repeated create_app() calls do not stack handlers."""
    logger = logging.getLogger("openbot")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
        logger.addHandler(handler)


def create_app(settings: Settings | None = None, services: Services | None = None) -> FastAPI:
    load_dotenv()
    _configure_logging()
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
    for r in (actors.router, bots.router, threads.router, messages.router, inbox.router, runs.router, tools.router,
              providers.router, events.router):
        api.include_router(r)
    app.include_router(public)
    app.include_router(api)

    dist = settings.frontend_dist
    if dist and Path(dist).is_dir():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")
    return app


app = create_app()
