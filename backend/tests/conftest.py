import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from openbot.config import Settings
from openbot.db.session import create_all, make_engine, make_session_factory
from openbot.main import create_app
from openbot.runtime.bus import EventBus
from openbot.seed import ensure_human_actor
from openbot.services import Services
from openbot.tools.registry import build_registry
from tests.fakes import ScriptedChatModel


@pytest.fixture
def settings(tmp_path) -> Settings:
    # A file-backed DB, not ":memory:": in-memory SQLite uses StaticPool, i.e. a single DBAPI
    # connection shared by every session, so once the actor system runs bots concurrently one
    # session's close (ROLLBACK) silently discards another's uncommitted writes.
    return Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db", workspace_root=tmp_path / "workspace",
                    tools_dir=tmp_path / "tools", seed_demo_bots=False, memory_reflection_delay=0.01,
                    webhook_retry_delays=[0.01, 0.01, 0.01], _env_file=None)


async def _noop(*_a, **_k):
    return []


_engines: list = []


@pytest.fixture(autouse=True)
async def _dispose_engines():
    """Autouse, so it tears down last: dispose every engine built during the test. Without this the
    aiosqlite connection threads outlive the test's event loop and warn when it is already closed."""
    yield
    while _engines:
        await _engines.pop().dispose()


async def build_test_services(settings: Settings, scripts: dict | None = None) -> Services:
    """Per-test file-backed DB, in-memory store/checkpointer, scripted models keyed by bot handle,
    @you present. Runner and actor system are attached here too (imported lazily)."""
    engine = make_engine(settings.database_url)
    _engines.append(engine)
    await create_all(engine)
    scripts = scripts if scripts is not None else {}
    services = Services(settings=settings, session_factory=make_session_factory(engine), _owned_resources=[engine])
    services.registry = build_registry(settings)
    services.bus = EventBus()
    services.store = InMemoryStore()
    services.checkpointer = InMemorySaver()
    iters: dict[str, object] = {}

    def factory(actor):
        # One iterator per handle, created lazily on first use, so a resumed run continues the script
        # and tests may still assign scripts[handle] in their body before the first run starts.
        if actor.handle not in iters:
            iters[actor.handle] = iter(list(scripts.get(actor.handle, [])))
        return ScriptedChatModel(messages=iters[actor.handle])

    services.model_factory = factory
    try:
        from openbot.runtime.memory import MemoryReflector
        services.reflector = MemoryReflector(services, settings.memory_reflection_delay)
        services.reflector.make_manager = lambda bot: type("M", (), {"ainvoke": staticmethod(_noop)})()
    except ImportError:
        pass
    try:
        from openbot.runtime.runner import Runner
        services.runner = Runner(services)
    except ImportError:
        pass
    try:
        import httpx

        from openbot.runtime.actors import ActorSystem
        services.http_client = httpx.AsyncClient()
        services.actors = ActorSystem(services, settings.max_concurrent_runs)
    except ImportError:
        pass
    await ensure_human_actor(services)
    return services


@pytest.fixture
def scripts() -> dict:
    return {}


@pytest.fixture
async def services(settings, scripts) -> Services:
    s = await build_test_services(settings, scripts)
    if s.actors is not None:
        await s.actors.start()
    yield s
    if s.actors is not None:
        await s.actors.stop()
    if s.http_client is not None:
        await s.http_client.aclose()


@pytest.fixture
async def client(settings, services):
    app = create_app(settings, services=services)
    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
