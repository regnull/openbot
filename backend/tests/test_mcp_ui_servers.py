"""MCP servers added from the Settings UI: stored in the database, merged with mcp.json at startup."""
import json
import sys
from pathlib import Path

from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from openbot.main import create_app
from openbot.mcp.config import McpServerConfig
from openbot.mcp.manager import McpManager
from openbot.tools.registry import ToolRegistry
from tests.conftest import build_test_services

STUB = str(Path(__file__).with_name("mcp_stub_server.py"))


class _Settings:
    tool_output_cap = 400
    public_url = "http://127.0.0.1:8000"


async def test_manager_can_add_and_remove_servers_at_runtime():
    reg = ToolRegistry()
    mgr = McpManager(servers=[], registry=reg, settings=_Settings(), storage=None)
    await mgr.start()
    try:
        assert mgr.statuses() == []
        st = await mgr.add_server(McpServerConfig(name="stub", transport="stdio", command=sys.executable, args=[STUB], source="db"))
        assert st.status == "connected" and st.source == "db" and reg.has("stub__add")
        assert mgr.has("stub")
        await mgr.remove_server("stub")
        assert not mgr.has("stub") and not reg.has("stub__add") and mgr.statuses() == []
    finally:
        await mgr.stop()


async def _app(settings, tmp_path, file_servers):
    settings.mcp_config = tmp_path / "mcp.json"
    settings.mcp_config.write_text(json.dumps({"mcpServers": file_servers}))
    settings.mcp_token_key_file = tmp_path / "k.key"
    services = await build_test_services(settings)
    return create_app(settings, services=services), services


async def test_add_list_and_remove_a_server_from_the_api(settings, tmp_path):
    app, _services = await _app(settings, tmp_path, {"filed": {"url": "https://filed.example.invalid/mcp", "enabled": False}})
    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/v1/mcp/servers", json={"name": "linear", "url": "https://mcp.example.invalid/mcp"})
        assert r.status_code == 201, r.text
        s = r.json()
        assert s["name"] == "linear" and s["source"] == "db" and s["transport"] == "http" and s["oauth"] is True
        assert s["status"] in ("connecting", "authorizing", "needs_auth", "error")
        rows = {x["name"]: x for x in (await c.get("/api/v1/mcp/servers")).json()}
        assert rows["filed"]["source"] == "file" and rows["linear"]["source"] == "db"
        assert "authorization_url" in rows["linear"]                     # the UI opens it when it appears
        # Validation.
        assert (await c.post("/api/v1/mcp/servers", json={"name": "linear", "url": "https://x.example/mcp"})).status_code == 409
        assert (await c.post("/api/v1/mcp/servers", json={"name": "filed", "url": "https://x.example/mcp"})).status_code == 409
        assert (await c.post("/api/v1/mcp/servers", json={"name": "bad name!", "url": "https://x.example/mcp"})).status_code == 422
        assert (await c.post("/api/v1/mcp/servers", json={"name": "plain", "url": "http://mcp.example.com/mcp"})).status_code == 422
        assert (await c.post("/api/v1/mcp/servers", json={"name": "local", "url": "http://localhost:8002/mcp"})).status_code == 201
        assert (await c.post("/api/v1/mcp/servers", json={"name": "nourl", "url": "mcp.example.com"})).status_code == 422
        # File servers cannot be removed from the UI; database ones can, and removal forgets credentials.
        assert (await c.delete("/api/v1/mcp/servers/filed")).status_code == 409
        assert (await c.delete("/api/v1/mcp/servers/linear")).status_code == 204
        assert (await c.delete("/api/v1/mcp/servers/linear")).status_code == 404
        names = {x["name"] for x in (await c.get("/api/v1/mcp/servers")).json()}
        assert names == {"filed", "local"}


async def test_added_servers_survive_a_restart(settings, tmp_path):
    fresh = settings.model_copy()
    app, _services = await _app(settings, tmp_path, {})
    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.post("/api/v1/mcp/servers", json={"name": "linear", "url": "https://mcp.example.invalid/mcp"})).status_code == 201
    fresh.mcp_config, fresh.mcp_token_key_file = settings.mcp_config, settings.mcp_token_key_file
    services2 = await build_test_services(fresh)
    app2 = create_app(fresh, services=services2)
    async with LifespanManager(app2), AsyncClient(transport=ASGITransport(app=app2), base_url="http://test") as c:
        rows = (await c.get("/api/v1/mcp/servers")).json()
        assert [r["name"] for r in rows] == ["linear"] and rows[0]["source"] == "db"


async def test_a_database_server_that_collides_with_the_file_is_skipped(settings, tmp_path):
    from openbot.db.models import McpServer
    app, services = await _app(settings, tmp_path, {"linear": {"url": "https://mcp.linear.app/mcp"}})
    async with services.session_factory() as s:
        s.add(McpServer(name="linear", url="https://other.example/mcp"))
        await s.commit()
    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        rows = (await c.get("/api/v1/mcp/servers")).json()
        assert len(rows) == 1 and rows[0]["source"] == "file" and rows[0]["url"] == "https://mcp.linear.app/mcp"
