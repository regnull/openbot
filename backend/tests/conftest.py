import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from openbot.config import Settings
from openbot.db.session import create_all, make_engine, make_session_factory
from openbot.main import create_app
from openbot.runtime.bus import EventBus
from openbot.services import Services
from openbot.tools.registry import build_registry


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(database_url="sqlite+aiosqlite:///:memory:", workspace_root=tmp_path / "workspace",
                    tools_dir=tmp_path / "tools", seed_demo_bots=False, memory_reflection_delay=0.01,
                    webhook_retry_delays=[0.01, 0.01, 0.01], _env_file=None)


@pytest.fixture
async def services(settings) -> Services:
    engine = make_engine(settings.database_url)
    await create_all(engine)
    services = Services(settings=settings, session_factory=make_session_factory(engine), _owned_resources=[engine])
    services.registry = build_registry(settings)
    services.bus = EventBus()
    return services


@pytest.fixture
async def client(settings, services):
    app = create_app(settings, services=services)
    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
