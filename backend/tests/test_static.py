from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from openbot.main import create_app


async def test_serves_frontend_when_dist_exists(settings, services, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<h1>OpenBot</h1>")
    settings.frontend_dist = dist
    app = create_app(settings, services=services)
    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert "OpenBot" in (await c.get("/")).text
        assert (await c.get("/api/v1/health")).status_code == 200
