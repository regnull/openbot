"""Fixes from the review of PR #37 (MCP servers). Each test names the failure it closes."""
import asyncio
import json
import sys
from pathlib import Path

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from langchain_core.tools import StructuredTool, ToolException
from mcp.shared.auth import OAuthToken

from openbot.main import create_app
from openbot.mcp.config import McpServerConfig
from openbot.mcp.manager import McpManager, _wrap, tool_name
from openbot.mcp.oauth import (
    AuthorizationRequired,
    DbTokenStorage,
    load_or_create_key,
)
from openbot.tools.registry import ToolRegistry
from tests.conftest import build_test_services

STUB = str(Path(__file__).with_name("mcp_stub_server.py"))


class _Settings:
    tool_output_cap = 400
    public_url = "http://127.0.0.1:8000"


def _stub(name="stub"):
    return McpServerConfig(name=name, transport="stdio", command=sys.executable, args=[STUB])


# --- 1. reflected XSS in the public callback -----------------------------------------------------------

async def test_callback_escapes_what_the_authorization_server_sends(settings, tmp_path):
    """The callback rendered error_description straight into HTML; a hostile authorization server
    (it legitimately holds the pending state) could run script on the app origin."""
    settings.mcp_config = tmp_path / "mcp.json"
    settings.mcp_config.write_text(json.dumps({"mcpServers": {"remote": {"url": "https://mcp.example.invalid/mcp"}}}))
    services = await build_test_services(settings)
    app = create_app(settings, services=services)
    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        redirect, callback = services.mcp.flows.handlers("remote", allow=lambda: True)
        waiter = asyncio.ensure_future(callback())
        await asyncio.sleep(0)
        await redirect("https://auth.example/authorize?state=s-xss")
        payload = "<img src=x onerror=\"fetch('//evil')\">"
        r = await c.get("/api/v1/mcp/oauth/callback", params={"state": "s-xss", "error": "access_denied", "error_description": payload})
        assert r.status_code == 200 and "<img" not in r.text and "&lt;img" in r.text
        with pytest.raises(RuntimeError):
            await waiter


# --- 2/3. boot never waits on a browser; a later 401 fails fast instead of hanging -----------------------

async def test_boot_connect_does_not_run_the_browser_flow_and_lands_in_needs_auth():
    """Stored-but-revoked tokens used to make boot wait 330s on a callback that could not arrive (the
    socket is not open during startup) and then record 'error', so every restart repeated the stall."""
    reg = ToolRegistry()
    cfg = McpServerConfig(name="remote", transport="http", url="https://mcp.example.invalid/mcp")
    mgr = McpManager(servers=[cfg], registry=reg, settings=_Settings(), storage=None, connect_timeout=5)

    async def fake_open(cfg, st):
        redirect, _ = mgr.flows.handlers(cfg.name, allow=lambda: mgr.interactive(cfg.name))
        await redirect("https://auth.example/authorize?state=boot")      # SDK asking for the browser

    mgr._open = fake_open
    t0 = asyncio.get_running_loop().time()
    st = await mgr.connect("remote")                                       # non-interactive: boot / reconnect path
    assert st.status == "needs_auth" and st.error is None
    assert asyncio.get_running_loop().time() - t0 < 2
    assert mgr.flows.authorization_url("remote") is None


async def test_interactive_connect_publishes_the_url_and_a_later_401_fails_fast():
    reg = ToolRegistry()
    cfg = McpServerConfig(name="remote", transport="http", url="https://mcp.example.invalid/mcp")
    mgr = McpManager(servers=[cfg], registry=reg, settings=_Settings(), storage=None, connect_timeout=5)
    handlers = {}

    async def fake_open(cfg, st):
        redirect, callback = mgr.flows.handlers(cfg.name, allow=lambda: mgr.interactive(cfg.name))
        handlers["redirect"] = redirect
        await redirect("https://auth.example/authorize?state=live")
        await callback()
        st.status, st.tools = "connected", []

    mgr._open = fake_open
    task = mgr.begin_connect("remote")                                     # the API path: interactive
    for _ in range(100):
        if mgr.flows.authorization_url("remote"):
            break
        await asyncio.sleep(0.01)
    assert mgr.flows.authorization_url("remote") == "https://auth.example/authorize?state=live"
    assert mgr.flows.complete("live", code="c") is True
    await task
    assert mgr.status("remote").status == "connected"
    # The session is up and the operator is no longer in the loop: a 401 mid-run must not park the run
    # on a callback nobody can answer.
    with pytest.raises(AuthorizationRequired):
        await handlers["redirect"]("https://auth.example/authorize?state=later")


# --- 4. a bad credential key marks the server errored instead of crashing boot ----------------------------

async def test_unusable_credential_storage_errors_that_server_only():
    reg = ToolRegistry()
    remote = McpServerConfig(name="remote", transport="http", url="https://mcp.example.invalid/mcp")

    def bad_storage(name, url=None):
        raise ValueError("Fernet key must be 32 url-safe base64-encoded bytes")

    mgr = McpManager(servers=[remote, _stub()], registry=reg, settings=_Settings(), storage=bad_storage, connect_timeout=10)
    await mgr.start()
    try:
        assert mgr.status("remote").status == "error" and "Fernet" in mgr.status("remote").error
        assert mgr.status("stub").status == "connected"
    finally:
        await mgr.stop()


# --- 5/6. sessions: swap on reconnect, notice when one dies ------------------------------------------------

async def test_reconnect_keeps_the_tools_registered_until_the_new_session_is_ready():
    reg = ToolRegistry()
    mgr = McpManager(servers=[_stub()], registry=reg, settings=_Settings(), storage=None)
    await mgr.start()
    try:
        seen_missing = False
        task = asyncio.ensure_future(mgr.connect("stub"))
        while not task.done():
            seen_missing = seen_missing or not reg.has("stub__add")
            await asyncio.sleep(0.005)
        assert not seen_missing and reg.has("stub__add") and mgr.status("stub").status == "connected"
    finally:
        await mgr.stop()


async def test_a_session_that_dies_is_noticed_tools_unregistered_status_error():
    reg = ToolRegistry()
    cfg = McpServerConfig(name="fragile", transport="stdio", command="x", args=[])
    mgr = McpManager(servers=[cfg], registry=reg, settings=_Settings(), storage=None)
    die = asyncio.Event()

    class FakeSession:
        """Behaves like the SDK's session under anyio: a transport failure cancels the body and the
        context exit raises the real error in place of the cancellation."""

        async def __aenter__(self):
            self.holder = asyncio.current_task()
            self.watch = asyncio.ensure_future(self._watch())
            return object()

        async def _watch(self):
            await die.wait()
            self.holder.cancel()

        async def __aexit__(self, et, ev, tb):
            self.watch.cancel()
            if et is asyncio.CancelledError and die.is_set():
                self.holder.uncancel()
                raise ConnectionError("child process exited")
            return False

    class FakeClient:
        def session(self, name):
            return FakeSession()

    async def fake_open(cfg, st):
        await mgr._start_session(cfg.name, FakeClient(), [StructuredTool.from_function(func=lambda x: x, name="t", description="t")])

    mgr._open = fake_open
    await mgr.connect("fragile")
    assert mgr.status("fragile").status == "connected" and reg.has("fragile__t")
    die.set()
    await asyncio.sleep(0.05)
    assert mgr.status("fragile").status == "error" and "child process exited" in mgr.status("fragile").error
    assert not reg.has("fragile__t")


# --- 7. tool wrapper: errors are errors, non-text blocks are placeholders, exceptions never fail the run ---

async def test_wrapper_reports_tool_errors_and_placeholders_for_binary_content():
    async def ok(x: str):
        return [{"type": "text", "text": f"got {x}"}, {"type": "image", "data": "A" * 20000, "mime_type": "image/png"}]

    async def bad(x: str):
        raise ToolException("boom: bad arg")

    async def transport_dead(x: str):
        raise ConnectionError("closed")

    good = _wrap(StructuredTool.from_function(coroutine=ok, name="t", description="t"), "s__t", 400)
    out = await good.ainvoke({"x": "1"})
    assert out.startswith("got 1") and "[image/png" in out and len(out) < 200 and "AAAA" not in out
    err = _wrap(StructuredTool.from_function(coroutine=bad, name="t", description="t", handle_tool_error=True), "s__t", 400)
    assert (await err.ainvoke({"x": "1"})).startswith("error: boom: bad arg")
    dead = _wrap(StructuredTool.from_function(coroutine=transport_dead, name="t", description="t"), "s__t", 400)
    assert (await dead.ainvoke({"x": "1"})).startswith("error: ConnectionError")


# --- 8. credentials are bound to the server URL ------------------------------------------------------------

async def test_tokens_stored_for_one_url_are_not_sent_to_another(services, tmp_path):
    key = load_or_create_key(None, tmp_path / "k.key")
    a = DbTokenStorage(services.session_factory, server="linear", key=key, url="https://mcp.linear.app/mcp")
    await a.set_tokens(OAuthToken(access_token="tok"))
    assert (await a.get_tokens()).access_token == "tok"
    b = DbTokenStorage(services.session_factory, server="linear", key=key, url="https://mcp.other.example/mcp")
    assert await b.get_tokens() is None                       # re-pointed name: the old token must not leak
    assert await a.get_tokens() is None                       # ...and the stale row is gone


# --- 9. composed tool names fit provider function-name rules -------------------------------------------------

def test_tool_names_are_sanitised_to_provider_rules():
    assert tool_name("github", "create_issue") == "github__create_issue"
    assert tool_name("internal-docs", "repo.search") == "internal-docs__repo_search"
    long = tool_name("internal-docs", "x" * 100)
    assert len(long) == 64 and long.startswith("internal-docs__")


# --- 10. bots keep working while an MCP server is down -------------------------------------------------------

async def test_bot_referencing_a_disconnected_mcp_tool_can_still_be_edited_and_runs_without_it(settings, tmp_path):
    settings.mcp_config = tmp_path / "mcp.json"
    settings.mcp_config.write_text(json.dumps({"mcpServers": {"remote": {"url": "https://mcp.example.invalid/mcp"}}}))
    services = await build_test_services(settings)
    app = create_app(settings, services=services)
    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/api/v1/mcp/servers")).json()[0]["status"] == "needs_auth"
        body = {"handle": "eng", "name": "E", "provider": "openai", "model": "gpt-5.5", "tool_names": ["remote__create_issue"]}
        r = await c.post("/api/v1/bots", json=body)
        assert r.status_code == 201, r.text                          # the server exists, even if not connected
        r = await c.patch(f"/api/v1/bots/{r.json()['id']}", json={"name": "E2"})
        assert r.status_code == 200, r.text
        assert (await c.post("/api/v1/bots", json={**body, "handle": "x", "tool_names": ["nope__tool"]})).status_code == 422
