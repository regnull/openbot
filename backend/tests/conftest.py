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
    return Settings(database_url="sqlite+aiosqlite:///:memory:", workspace_root=tmp_path / "workspace",
                    tools_dir=tmp_path / "tools", seed_demo_bots=False, memory_reflection_delay=0.01,
                    webhook_retry_delays=[0.01, 0.01, 0.01], _env_file=None)


async def _noop(*_a, **_k):
    return []


async def build_test_services(settings: Settings, scripts: dict | None = None) -> Services:
    """In-memory DB/store/checkpointer, scripted models keyed by bot handle, @you present.
    Runner/actor system are attached in Tasks 14/15 (they import lazily so earlier tasks still work)."""
    engine = make_engine(settings.database_url)
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


@pytest.fixture
async def client(settings, services):
    app = create_app(settings, services=services)
    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
