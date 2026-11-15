"""Shutdown must cancel a connection even before its session is registered."""
import asyncio
from contextlib import asynccontextmanager

import pytest

from openbot.mcp.config import McpServerConfig
from openbot.mcp.manager import McpManager
from openbot.tools.registry import ToolRegistry


@pytest.mark.parametrize("phase", ["session_entry", "tool_loading"])
async def test_stop_cancels_pending_connection_and_releases_session(monkeypatch, phase):
    blocked = asyncio.Event()
    released = asyncio.Event()
    holder_tasks = []

    class Client:
        def __init__(self, connections):
            pass

        @asynccontextmanager
        async def session(self, name):
            holder_tasks.append(asyncio.current_task())
            try:
                if phase == "session_entry":
                    blocked.set()
                    await asyncio.Event().wait()
                yield object()
            finally:
                assert asyncio.current_task() is holder_tasks[0]
                released.set()

    async def load_tools(session):
        blocked.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("openbot.mcp.manager.MultiServerMCPClient", Client)
    monkeypatch.setattr("openbot.mcp.manager.load_mcp_tools", load_tools)
    registry = ToolRegistry()
    manager = McpManager(
        servers=[McpServerConfig(name="pending", transport="http", url="https://example.invalid/mcp",
                                 headers={"Authorization": "Bearer test"})],
        registry=registry, settings=object(), storage=None,
    )
    connection = manager.begin_connect("pending")
    try:
        await asyncio.wait_for(blocked.wait(), 1)
        await asyncio.wait_for(manager.stop(), 1)
        assert connection.cancelled()
        assert released.is_set()
        assert all(task.done() for task in holder_tasks)
        assert manager.status("pending").status == "disconnected"
        assert not manager._sessions
        assert not manager._tasks
        assert registry.specs() == []
    finally:
        connection.cancel()
        for task in holder_tasks:
            task.cancel()
        await asyncio.gather(connection, *holder_tasks, return_exceptions=True)
