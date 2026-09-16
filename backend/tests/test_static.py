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


async def test_spa_routes_fall_back_to_index_but_missing_assets_and_api_do_not(settings, services, tmp_path):
    """Refreshing the browser on /inbox or /bots/<id> must load the app: those paths exist only in the
    frontend router. Starlette's html mode has no history fallback (it only looks for 404.html), so a
    deep link 404ed. Real files, missing assets and the API keep their own answers."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<h1>OpenBot</h1>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    settings.frontend_dist = dist
    app = create_app(settings, services=services)
    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        for path in ("/inbox", "/bots/abc-123", "/threads/x?tab=usage"):
            r = await c.get(path)
            assert r.status_code == 200 and "OpenBot" in r.text, path
        assert (await c.get("/assets/app.js")).text == "console.log(1)"
        assert (await c.get("/assets/missing.js")).status_code == 404
        assert (await c.get("/api/v1/nope")).status_code == 404
        assert (await c.get("/favicon.ico")).status_code == 404          # file-looking paths are not the app
