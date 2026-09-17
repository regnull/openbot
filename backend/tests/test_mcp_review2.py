"""Fixes from the review of PR #40 (MCP configuration in the database)."""
import asyncio
import sys
from pathlib import Path

from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from openbot.db.models import McpServer
from openbot.db.session import make_engine, run_migrations
from openbot.main import create_app
from openbot.mcp.config import build_server
from openbot.mcp.oauth import load_or_create_key
from openbot.mcp.store import MASK, McpServerStore
from tests.conftest import build_test_services

STUB = str(Path(__file__).with_name("mcp_stub_server.py"))


async def test_saving_masked_secrets_back_keeps_the_stored_values(services, tmp_path):
    """The UI shows masks and echoes them back on Save; that must never overwrite the real secret."""
    store = McpServerStore(services.session_factory, load_or_create_key(None, tmp_path / "k.key"))
    await store.upsert({"name": "gh", "command": "npx", "env": {"TOKEN": "real", "OTHER": "x"}})
    await store.update("gh", {"env": {"TOKEN": MASK, "OTHER": "", "NEW": "n"}, "args": ["-y"]})
    cfg = {c.name: c for c in await store.configs(env={})}["gh"]
    assert cfg.env == {"TOKEN": "real", "OTHER": "x", "NEW": "n"} and cfg.args == ["-y"]


def test_variable_references_are_checked_after_expansion():
    """`${VAR}` skipped the https rule at write time and nothing re-checked the expanded URL."""
    cfg = build_server("x", {"url": "http://api.example.com/mcp?x=${HOME}", "headers": {"Authorization": "Bearer k"}}, env={"HOME": "/h"})
    assert cfg.error and "https" in cfg.error
    ok = build_server("x", {"url": "https://${HOST}/mcp"}, env={"HOST": "mcp.example.com"})
    assert ok.error is None and ok.url == "https://mcp.example.com/mcp"
    local = build_server("x", {"url": "http://${HOST}:8002/mcp"}, env={"HOST": "localhost"})
    assert local.error is None


async def test_listing_shows_the_stored_url_not_the_expanded_one(settings, tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_HOST", "internal.example.com")
    services = await build_test_services(settings)
    app = create_app(settings, services=services)
    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/v1/mcp/servers", json={"name": "corp", "url": "https://${MCP_HOST}/mcp", "headers": {"Authorization": "Bearer k"}})
        assert r.status_code == 201, r.text
        assert r.json()["url"] == "https://${MCP_HOST}/mcp"                   # what the edit dialog must round-trip


async def test_unreadable_secrets_are_kept_not_overwritten_and_the_server_is_errored(services, tmp_path):
    good = McpServerStore(services.session_factory, load_or_create_key(None, tmp_path / "k1.key"))
    await good.upsert({"name": "linear", "url": "https://mcp.linear.app/mcp", "headers": {"Authorization": "Bearer real"}})
    async with services.session_factory() as s:
        blob_before = (await s.get(McpServer, "linear")).secrets
    rotated = McpServerStore(services.session_factory, load_or_create_key(None, tmp_path / "k2.key"))
    cfg = {c.name: c for c in await rotated.configs(env={})}["linear"]
    assert cfg.error and "cannot be read" in cfg.error                     # not silently reclassified as OAuth
    await rotated.update("linear", {"enabled": False})                      # a one-field toggle...
    async with services.session_factory() as s:
        row = await s.get(McpServer, "linear")
    assert row.secrets == blob_before and row.enabled is False               # ...keeps the old ciphertext
    cfg = {c.name: c for c in await good.configs(env={})}["linear"]
    assert cfg.headers == {"Authorization": "Bearer real"}                   # restoring the key recovers it


async def test_a_bad_credential_key_does_not_take_the_boot_down(settings, tmp_path):
    """The key is only touched when a secret must be encrypted or decrypted, so a broken key leaves the
    app (and servers without secrets) working, and fails the one operation that needs it with a clear message."""
    settings.mcp_token_key = "not-a-fernet-key"
    services = await build_test_services(settings)
    app = create_app(settings, services=services)
    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/api/v1/health")).status_code == 200
        assert (await c.get("/api/v1/mcp/servers")).json() == []
        assert (await c.post("/api/v1/mcp/servers", json={"name": "s", "command": sys.executable, "args": [STUB]})).status_code == 201
        r = await c.post("/api/v1/mcp/servers", json={"name": "secret", "url": "https://x.example/mcp", "headers": {"Authorization": "Bearer k"}})
        assert r.status_code == 503 and "MCP_TOKEN_KEY" in r.json()["detail"]
        assert {x["name"] for x in (await c.get("/api/v1/mcp/servers")).json()} == {"s"}     # nothing half-stored


async def test_a_bad_key_with_stored_secrets_errors_those_servers_not_the_boot(settings, tmp_path):
    good = await build_test_services(settings)
    app = create_app(settings, services=good)
    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.post("/api/v1/mcp/servers", json={"name": "secret", "url": "https://x.example/mcp", "headers": {"Authorization": "Bearer k"}})).status_code == 201
    broken = settings.model_copy()
    broken.mcp_token_key = "not-a-fernet-key"
    services = await build_test_services(broken)
    app2 = create_app(broken, services=services)
    async with LifespanManager(app2), AsyncClient(transport=ASGITransport(app=app2), base_url="http://test") as c:
        assert (await c.get("/api/v1/health")).status_code == 200
        r = await c.get("/api/v1/mcp/servers")
        assert r.status_code == 503 and "MCP_TOKEN_KEY" in r.json()["detail"]


async def test_fresh_install_does_not_write_a_key_file_until_a_secret_needs_it(settings, tmp_path):
    services = await build_test_services(settings)
    app = create_app(settings, services=services)
    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/api/v1/mcp/servers")).json() == []
        assert (await c.post("/api/v1/mcp/servers", json={"name": "s", "command": sys.executable, "args": [STUB]})).status_code == 201
        assert not settings.mcp_token_key_file.exists()                                        # no secret yet
        assert (await c.post("/api/v1/mcp/servers", json={"name": "t", "command": sys.executable, "args": [STUB], "env": {"K": "v"}})).status_code == 201
        assert settings.mcp_token_key_file.exists()


async def test_patch_returns_promptly_and_connects_in_the_background(settings, tmp_path):
    services = await build_test_services(settings)
    app = create_app(settings, services=services)
    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.post("/api/v1/mcp/servers", json={"name": "stub", "command": sys.executable, "args": [STUB]})).status_code == 201
        t0 = asyncio.get_running_loop().time()
        r = await c.patch("/api/v1/mcp/servers/stub", json={"enabled": False})
        assert r.json()["status"] == "disabled"
        r = await c.patch("/api/v1/mcp/servers/stub", json={"enabled": True})
        assert asyncio.get_running_loop().time() - t0 < 5 and r.json()["status"] in ("connecting", "connected")
        for _ in range(100):
            if (await c.get("/api/v1/mcp/servers")).json()[0]["status"] == "connected":
                break
            await asyncio.sleep(0.05)
        assert (await c.get("/api/v1/mcp/servers")).json()[0]["tools"] == ["stub__add", "stub__echo"]


async def test_downgrade_survives_stdio_rows(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    await run_migrations(url)
    engine = make_engine(url)
    async with engine.begin() as conn:
        await conn.execute(text("insert into mcp_servers (name, transport, command, enabled, created_at, updated_at) "
                                "values ('local', 'stdio', 'npx', 1, '2026-01-01', '2026-01-01')"))
    await engine.dispose()
    from openbot.db.session import downgrade_migrations
    await downgrade_migrations(url, "0011")
    engine = make_engine(url)
    async with engine.connect() as conn:
        version = (await conn.execute(text("select version_num from alembic_version"))).scalar()
        names = (await conn.execute(text("select name from mcp_servers"))).scalars().all()
    await engine.dispose()
    assert version == "0011" and names == []                                   # stdio rows cannot exist at 0011; dropped, not crashed


async def test_bot_editor_data_lists_granted_tools_of_a_disconnected_server(settings, tmp_path):
    """The bot keeps tool_names for a server that is disabled; the API must still let the editor show and
    ungrant them: GET /bots/{id} returns them, and /tools?include=<names> reports which are unavailable."""
    services = await build_test_services(settings)
    app = create_app(settings, services=services)
    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.post("/api/v1/mcp/servers", json={"name": "stub", "command": sys.executable, "args": [STUB]})).status_code == 201
        for _ in range(100):
            if (await c.get("/api/v1/mcp/servers")).json()[0]["status"] == "connected":
                break
            await asyncio.sleep(0.05)
        r = await c.post("/api/v1/bots", json={"handle": "eng", "name": "E", "provider": "openai", "model": "gpt-5.5", "tool_names": ["stub__add"]})
        assert r.status_code == 201, r.text
        bot = r.json()
        await c.patch("/api/v1/mcp/servers/stub", json={"enabled": False})
        names = {t["name"] for t in (await c.get("/api/v1/tools")).json()["tools"]}
        assert "stub__add" not in names
        assert (await c.get(f"/api/v1/bots/{bot['id']}")).json()["tool_names"] == ["stub__add"]
        r = await c.patch(f"/api/v1/bots/{bot['id']}", json={"tool_names": []})
        assert r.status_code == 200 and r.json()["tool_names"] == []
