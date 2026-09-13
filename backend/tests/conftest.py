import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from openbot.config import Settings
from openbot.main import create_app


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        workspace_root=tmp_path / "workspace",
        tools_dir=tmp_path / "tools",
        seed_demo_bots=False,
        _env_file=None,
    )


@pytest.fixture
async def client(settings):
    app = create_app(settings)
    async with LifespanManager(app), AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
