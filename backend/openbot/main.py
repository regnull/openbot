from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

import httpx
from dotenv import find_dotenv, load_dotenv
from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from openbot.api import actors, bots, events, inbox, messages, providers, runs, threads, tools
from openbot.api.deps import require_api_key
from openbot.config import Settings, get_settings
from openbot.db.session import create_all, make_engine, make_session_factory, run_migrations
from openbot.logsetup import configure_logging
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
    _log_startup(settings, services)
    return services


def _log_startup(settings: Settings, services: Services) -> None:
    """One line with every path the process actually resolved. Relative settings such as
    WORKSPACE_ROOT=./workspace depend on the cwd the server was started from, so this is the first
    thing to check when a bot reports files that "do not exist"."""
    dotenv = find_dotenv(usecwd=True)
    log.info("startup: cwd=%s dotenv=%s workspace_root=%s (WORKSPACE_ROOT=%s) tools_dir=%s database_url=%s "
             "bot_model=%s frontend_dist=%s log_file=%s log_level=%s tools=%d",
             os.getcwd(), dotenv or "<none>", Path(settings.workspace_root).resolve(), settings.workspace_root,
             Path(settings.tools_dir).resolve(), settings.database_url, settings.bot_model or settings.openrouter_model or "<default>",
             settings.frontend_dist, Path(settings.log_file).resolve(), settings.log_level,
             len(services.registry.specs()) if services.registry is not None else 0)


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
        # Reflection is debounced by MEMORY_REFLECTION_DELAY (30s by default), so on a normal
        # restart the last run's memories are still sitting in the pending map. Run them now rather
        # than dropping them -- but bounded, so a hung provider call cannot wedge the shutdown.
        try:
            await asyncio.wait_for(services.reflector.flush(), timeout=10)
        except TimeoutError:
            log.warning("memory reflection did not finish within 10s; dropping pending memories")
        except Exception:
            log.exception("memory reflection failed during shutdown")
        await services.reflector.shutdown()


_BUSES_TO_CLOSE: list = []


def _install_uvicorn_exit_hook() -> None:
    """Wrap `uvicorn.Server.handle_exit` so the first shutdown signal also closes every registered bus.

    uvicorn's shutdown order is: stop accepting, wait for open connections to drain, then run the
    lifespan shutdown. An event-stream connection never drains on its own, so the lifespan hook is
    too late to end it and Ctrl+C hangs until a second Ctrl+C force-cancels the connections (logged
    as "Exception in ASGI application"). The same approach sse-starlette takes. It must run at import:
    uvicorn loads the app module *before* it installs its signal handlers, and those handlers bind
    `handle_exit` at that moment, so a patch applied any later is never called.
    """
    try:
        from uvicorn.server import Server
    except ImportError:                     # not running under uvicorn (other servers, tooling)
        return
    if getattr(Server.handle_exit, "_openbot_closes_buses", False):
        return
    original = Server.handle_exit

    def handle_exit(self, sig, frame):
        original(self, sig, frame)
        for bus in _BUSES_TO_CLOSE:
            bus.close()

    handle_exit._openbot_closes_buses = True  # type: ignore[attr-defined]
    Server.handle_exit = handle_exit


def close_buses_on_uvicorn_exit(bus) -> Callable[[], None]:
    """Register `bus` to be closed on uvicorn's first shutdown signal; returns an unregister function."""
    _BUSES_TO_CLOSE.append(bus)

    def unregister() -> None:
        if bus in _BUSES_TO_CLOSE:
            _BUSES_TO_CLOSE.remove(bus)

    return unregister


_install_uvicorn_exit_hook()


class SpaStaticFiles(StaticFiles):
    """Static files with a single-page-app history fallback.

    Routes such as /inbox or /bots/<id> exist only in the frontend router, so a browser refresh on one
    of them must load index.html and let the app route. Starlette's html mode only falls back to a
    404.html, so deep links 404ed. Unknown API paths and paths whose last segment looks like a file
    (has an extension) are left alone: a missing asset must stay a 404, not silently become the app shell.
    """

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            # Not the app: a real 404 from the API namespace, or a path that names a file (has an extension).
            if exc.status_code != 404 or path.startswith("api/") or "." in path.rsplit("/", 1)[-1]:
                raise
            return await super().get_response("index.html", scope)


def create_app(settings: Settings | None = None, services: Services | None = None) -> FastAPI:
    load_dotenv()
    settings = settings or get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        owned = app.state.services is None
        if owned:
            app.state.services = await build_services(settings)
        await start_background(app.state.services)
        unregister_bus = close_buses_on_uvicorn_exit(app.state.services.bus)
        try:
            yield
        finally:
            unregister_bus()
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
        if not (Path(dist) / "index.html").is_file():
            log.warning("frontend_dist %s has no index.html; run `make build` (or `make run`, which builds first) "
                        "or the UI will 404", Path(dist).resolve())
        app.mount("/", SpaStaticFiles(directory=str(dist), html=True), name="frontend")
    return app


app = create_app()
