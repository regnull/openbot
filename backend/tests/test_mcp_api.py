"""MCP endpoints and the public OAuth callback."""
import asyncio
import json
import sys
from pathlib import Path

from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from openbot.main import create_app
from tests.conftest import build_test_services

STUB = str(Path(__file__).with_name("mcp_stub_server.py"))


def _config(tmp_path, servers):
    p = tmp_path / "mcp.json"
    p.write_text(json.dumps({"mcpServers": servers}))
    return p


async def _app(settings, tmp_path, servers):
    settings.mcp_config = _config(tmp_path, servers)
    settings.mcp_token_key_file = tmp_path / "k.key"
    services = await build_test_services(settings)
    app = create_app(settings, services=services)
    return app, services


async def test_servers_are_listed_with_status_and_tools_and_show_up_in_the_tool_list(settings, tmp_path):
    app, services = await _app(settings, tmp_path, {
        "stub": {"command": sys.executable, "args": [STUB]},
        "remote": {"url": "https://mcp.example.invalid/mcp"},          # OAuth, no credentials: waits for the operator
        "off": {"url": "https://x/mcp", "enabled": False},
    })
    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        rows = {r["name"]: r for r in (await c.get("/api/v1/mcp/servers")).json()}
        assert rows["stub"]["status"] == "connected" and rows["stub"]["tools"] == ["stub__add", "stub__echo"] and rows["stub"]["oauth"] is False
        assert rows["remote"]["status"] == "needs_auth" and rows["remote"]["oauth"] is True and rows["remote"]["tools"] == []
        assert rows["off"]["status"] == "disabled"
        tools = {t["name"]: t for t in (await c.get("/api/v1/tools")).json()["tools"]}
        assert tools["stub__add"]["source"] == "mcp:stub" and "Add two integers" in tools["stub__add"]["description"]
        # A bot can select the tool like any other.
        r = await c.post("/api/v1/bots", json={"handle": "eng", "name": "E", "provider": "openai", "model": "gpt-5.5", "tool_names": ["stub__add"]})
        assert r.status_code == 201, r.text
        # Disconnect removes the tools; connect brings them back.
        assert (await c.post("/api/v1/mcp/servers/stub/disconnect")).json()["status"] == "disconnected"
        assert "stub__add" not in {t["name"] for t in (await c.get("/api/v1/tools")).json()["tools"]}
        assert (await c.post("/api/v1/mcp/servers/stub/connect")).json()["status"] == "connected"
        assert "stub__add" in {t["name"] for t in (await c.get("/api/v1/tools")).json()["tools"]}
        assert (await c.post("/api/v1/mcp/servers/nope/connect")).status_code == 404
        assert (await c.post("/api/v1/mcp/servers/off/connect")).status_code == 409
    assert services.mcp.status("stub").status == "disconnected"           # lifespan shutdown closed the session


async def test_connect_returns_the_authorization_url_and_the_callback_completes_the_flow(settings, tmp_path, monkeypatch):
    """The SDK's OAuth provider is not exercised here; the manager's flow plumbing is. A fake connect
    stands in for the provider: it registers handlers, publishes the URL, and waits for the code."""
    app, services = await _app(settings, tmp_path, {"remote": {"url": "https://mcp.example.invalid/mcp"}})
    got = {}

    async def fake_open(cfg, st):
        redirect, callback = services.mcp.flows.handlers(cfg.name)
        st.status = "authorizing"
        await redirect("https://auth.example/authorize?client_id=c&state=st-1")
        got["code"], _ = await callback()
        st.status, st.tools = "connected", ["remote__x"]

    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        monkeypatch.setattr(services.mcp, "_open", fake_open)
        r = await c.post("/api/v1/mcp/servers/remote/connect")
        assert r.json() == {"status": "authorizing", "authorization_url": "https://auth.example/authorize?client_id=c&state=st-1"}
        assert (await c.get("/api/v1/mcp/servers")).json()[0]["status"] == "authorizing"
        # The browser comes back to the public callback (no API key) with the code.
        r = await c.get("/api/v1/mcp/oauth/callback", params={"code": "the-code", "state": "st-1"})
        assert r.status_code == 200 and "text/html" in r.headers["content-type"] and "/settings" in r.text
        await asyncio.sleep(0.05)
        assert got["code"] == "the-code"
        assert (await c.get("/api/v1/mcp/servers")).json()[0]["status"] == "connected"
        # Unknown or reused state is rejected, and an error from the authorization server is surfaced.
        assert (await c.get("/api/v1/mcp/oauth/callback", params={"code": "x", "state": "st-1"})).status_code == 400
        assert (await c.get("/api/v1/mcp/oauth/callback", params={"error": "access_denied", "state": "zzz"})).status_code == 400
        # Forgetting credentials returns the server to needs_auth.
        assert (await c.delete("/api/v1/mcp/servers/remote/credentials")).json()["status"] == "needs_auth"


async def test_callback_requires_no_api_key(settings, tmp_path):
    settings.openbot_api_key = "secret"
    app, _ = await _app(settings, tmp_path, {})
    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/api/v1/mcp/servers")).status_code == 401
        assert (await c.get("/api/v1/mcp/oauth/callback", params={"code": "x", "state": "none"})).status_code == 400   # reached, rejected on state


async def test_migration_adds_mcp_credentials_table(tmp_path):
    from sqlalchemy import inspect

    from openbot.db.session import make_engine, run_migrations
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    await run_migrations(url)
    engine = make_engine(url)
    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
    await engine.dispose()
    assert "mcp_credentials" in tables
