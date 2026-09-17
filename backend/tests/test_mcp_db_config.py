"""MCP server configuration lives in the database; mcp.json is imported once and then ignored."""
import asyncio
import json
import sys
from pathlib import Path

from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect, select

from openbot.db.models import McpServer
from openbot.db.session import make_engine, run_migrations
from openbot.main import create_app
from openbot.mcp.oauth import load_or_create_key
from openbot.mcp.store import McpServerStore, import_mcp_file
from tests.conftest import build_test_services

STUB = str(Path(__file__).with_name("mcp_stub_server.py"))


async def test_store_round_trip_encrypts_secrets_and_expands_variables(services, tmp_path):
    store = McpServerStore(services.session_factory, load_or_create_key(None, tmp_path / "k.key"))
    await store.upsert({"name": "gh", "command": "npx", "args": ["-y", "server-github"], "env": {"TOKEN": "${GH}", "PLAIN": "shh"}, "cwd": "/tmp"})
    await store.upsert({"name": "linear", "url": "https://mcp.linear.app/mcp", "headers": {"Authorization": "Bearer secret-1"}})
    async with services.session_factory() as s:
        rows = {r.name: r for r in (await s.execute(select(McpServer))).scalars()}
    assert rows["gh"].transport == "stdio" and rows["gh"].command == "npx" and rows["gh"].args == ["-y", "server-github"]
    assert "shh" not in (rows["gh"].secrets or "") and "secret-1" not in (rows["linear"].secrets or "")
    cfgs = {c.name: c for c in await store.configs(env={"GH": "ghp_1"})}
    assert cfgs["gh"].env == {"TOKEN": "ghp_1", "PLAIN": "shh"} and cfgs["gh"].cwd == "/tmp" and cfgs["gh"].source == "db"
    assert cfgs["linear"].headers == {"Authorization": "Bearer secret-1"} and cfgs["linear"].oauth is False
    cfgs = {c.name: c for c in await store.configs(env={})}
    assert cfgs["gh"].error and "GH" in cfgs["gh"].error                 # unset variable errors that server only
    assert cfgs["linear"].error is None
    # Partial update: "" for an existing secret keeps the stored value; new keys are added; enabled toggles.
    await store.update("linear", {"headers": {"Authorization": "", "X-Team": "eng"}, "enabled": False})
    cfg = {c.name: c for c in await store.configs(env={})}["linear"]
    assert cfg.headers == {"Authorization": "Bearer secret-1", "X-Team": "eng"} and cfg.enabled is False
    assert (await store.get("linear"))["headers"] == {"Authorization": "••••••••", "X-Team": "••••••••"}   # masked for the UI
    await store.delete("gh")
    assert [c.name for c in await store.configs(env={})] == ["linear"]


async def test_mcp_json_is_imported_once_and_variables_are_kept_unexpanded(services, tmp_path):
    store = McpServerStore(services.session_factory, load_or_create_key(None, tmp_path / "k.key"))
    p = tmp_path / "mcp.json"
    p.write_text(json.dumps({"mcpServers": {
        "gh": {"command": "npx", "args": ["x"], "env": {"TOKEN": "${GH}"}},
        "linear": {"url": "https://mcp.linear.app/mcp", "enabled": False},
    }}))
    assert await import_mcp_file(store, p) == ["gh", "linear"]
    assert await import_mcp_file(store, p) == []                             # idempotent
    await store.update("linear", {"enabled": True})
    assert await import_mcp_file(store, p) == []                             # never overwrites what the operator changed
    cfgs = {c.name: c for c in await store.configs(env={"GH": "tok"})}
    assert cfgs["gh"].env == {"TOKEN": "tok"} and cfgs["linear"].enabled is True
    assert await import_mcp_file(store, tmp_path / "missing.json") == []


async def _app(settings, tmp_path, file_servers=None):
    settings.mcp_config = tmp_path / "mcp.json"
    if file_servers is not None:
        settings.mcp_config.write_text(json.dumps({"mcpServers": file_servers}))
    settings.mcp_token_key_file = tmp_path / "k.key"
    services = await build_test_services(settings)
    return create_app(settings, services=services), services


async def test_api_manages_stdio_and_http_servers_with_masked_secrets(settings, tmp_path):
    app, _services = await _app(settings, tmp_path)
    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/v1/mcp/servers", json={"name": "stub", "command": sys.executable, "args": [STUB], "env": {"GREETING": "hi"}})
        assert r.status_code == 201, r.text
        for _ in range(100):
            row = next(x for x in (await c.get("/api/v1/mcp/servers")).json() if x["name"] == "stub")
            if row["status"] == "connected":
                break
            await asyncio.sleep(0.05)
        assert row["status"] == "connected" and row["transport"] == "stdio" and row["tools"] == ["stub__add", "stub__echo"]
        assert row["command"] == sys.executable and row["args"] == [STUB] and row["env"] == {"GREETING": "••••••••"}
        r = await c.post("/api/v1/mcp/servers", json={"name": "linear", "url": "https://mcp.example.invalid/mcp", "headers": {"Authorization": "Bearer k"}})
        assert r.status_code == 201 and r.json()["headers"] == {"Authorization": "••••••••"} and r.json()["oauth"] is False
        # Disable: tools go away; enable: they come back.
        r = await c.patch("/api/v1/mcp/servers/stub", json={"enabled": False})
        assert r.status_code == 200 and r.json()["status"] == "disabled"
        assert "stub__add" not in {t["name"] for t in (await c.get("/api/v1/tools")).json()["tools"]}
        r = await c.patch("/api/v1/mcp/servers/stub", json={"enabled": True})
        assert r.json()["status"] in ("connecting", "connected")           # reconnects in the background
        for _ in range(100):
            if (await c.get("/api/v1/mcp/servers")).json()[0]["status"] == "connected":
                break
            await asyncio.sleep(0.05)
        assert "stub__add" in {t["name"] for t in (await c.get("/api/v1/tools")).json()["tools"]}
        # Editing keeps masked secrets when the UI sends them back blank.
        r = await c.patch("/api/v1/mcp/servers/linear", json={"headers": {"Authorization": "", "X-Team": "eng"}})
        assert r.json()["headers"] == {"Authorization": "••••••••", "X-Team": "••••••••"}
        # Validation and removal.
        assert (await c.post("/api/v1/mcp/servers", json={"name": "both", "url": "https://x/mcp", "command": "x"})).status_code == 422
        assert (await c.post("/api/v1/mcp/servers", json={"name": "neither"})).status_code == 422
        assert (await c.patch("/api/v1/mcp/servers/nope", json={"enabled": False})).status_code == 404
        assert (await c.delete("/api/v1/mcp/servers/stub")).status_code == 204
        assert {x["name"] for x in (await c.get("/api/v1/mcp/servers")).json()} == {"linear"}


async def test_file_servers_appear_after_import_and_the_file_is_then_ignored(settings, tmp_path):
    app, _services = await _app(settings, tmp_path, {"filed": {"url": "https://filed.example.invalid/mcp", "enabled": False}})
    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        rows = (await c.get("/api/v1/mcp/servers")).json()
        assert [r["name"] for r in rows] == ["filed"] and rows[0]["status"] == "disabled" and rows[0]["source"] == "db"
        assert (await c.delete("/api/v1/mcp/servers/filed")).status_code == 204      # imported servers are ordinary rows
    # A restart with the file still present does not resurrect the deleted server.
    fresh = settings.model_copy()
    services2 = await build_test_services(fresh)
    app2 = create_app(fresh, services=services2)
    async with LifespanManager(app2), AsyncClient(transport=ASGITransport(app=app2), base_url="http://test") as c:
        assert (await c.get("/api/v1/mcp/servers")).json() == []


async def test_migration_adds_transport_columns(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    await run_migrations(url)
    engine = make_engine(url)
    async with engine.connect() as conn:
        cols = await conn.run_sync(lambda c: {col["name"] for col in inspect(c).get_columns("mcp_servers")})
    await engine.dispose()
    assert {"name", "transport", "url", "command", "args", "cwd", "secrets", "enabled"} <= cols and "headers" not in cols
