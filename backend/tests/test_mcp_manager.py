"""McpManager: connects configured servers, registers their tools, survives bad ones."""
import sys
from pathlib import Path

from openbot.mcp.config import McpServerConfig
from openbot.mcp.manager import McpManager
from openbot.tools.registry import ToolRegistry

STUB = str(Path(__file__).with_name("mcp_stub_server.py"))


def _stub(name="stub"):
    return McpServerConfig(name=name, transport="stdio", command=sys.executable, args=[STUB])


class _Settings:
    tool_output_cap = 60
    public_url = "http://127.0.0.1:8000"


async def test_connects_registers_prefixed_tools_and_calls_them():
    reg = ToolRegistry()
    mgr = McpManager(servers=[_stub()], registry=reg, settings=_Settings(), storage=None)
    await mgr.start()
    try:
        st = mgr.status("stub")
        assert st.status == "connected" and sorted(st.tools) == ["stub__add", "stub__echo"] and st.error is None
        assert reg.has("stub__add") and reg.specs()[0].source == "mcp:stub"
        out = await reg.get("stub__add").ainvoke({"a": 2, "b": 3})
        assert "5" in str(out)
    finally:
        await mgr.stop()
    assert not reg.has("stub__add")                                      # stop unregisters


async def test_results_are_capped_like_builtin_tools():
    reg = ToolRegistry()
    mgr = McpManager(servers=[_stub()], registry=reg, settings=_Settings(), storage=None)
    await mgr.start()
    try:
        out = await reg.get("stub__echo").ainvoke({"text": "y" * 500})
        assert len(str(out)) < 200 and "[truncated" in str(out)
    finally:
        await mgr.stop()


async def test_a_broken_server_is_reported_without_stopping_the_others():
    reg = ToolRegistry()
    bad = McpServerConfig(name="bad", transport="stdio", command="/nonexistent/binary", args=[])
    unset = McpServerConfig(name="unset", transport="http", url="https://x/mcp", error="environment variable K is not set")
    off = McpServerConfig(name="off", transport="http", url="https://x/mcp", enabled=False)
    mgr = McpManager(servers=[bad, _stub(), unset, off], registry=reg, settings=_Settings(), storage=None, connect_timeout=10)
    await mgr.start()
    try:
        assert mgr.status("stub").status == "connected"
        assert mgr.status("bad").status == "error" and mgr.status("bad").error
        assert mgr.status("unset").status == "error" and "K" in mgr.status("unset").error
        assert mgr.status("off").status == "disabled"
        assert [s.name for s in mgr.statuses()] == ["bad", "stub", "unset", "off"]
    finally:
        await mgr.stop()


async def test_disconnect_and_reconnect_one_server():
    reg = ToolRegistry()
    mgr = McpManager(servers=[_stub()], registry=reg, settings=_Settings(), storage=None)
    await mgr.start()
    try:
        await mgr.disconnect("stub")
        assert mgr.status("stub").status == "disconnected" and not reg.has("stub__add")
        await mgr.connect("stub")
        assert mgr.status("stub").status == "connected" and reg.has("stub__add")
    finally:
        await mgr.stop()
