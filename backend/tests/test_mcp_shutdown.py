"""Shutdown must cancel a connection even before its session is registered."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import anyio
import pytest
from anyio.lowlevel import checkpoint
from langchain_core.tools import StructuredTool

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


@pytest.mark.parametrize("failure", ["session_timeout", "tools_timeout", "tools_error"])
async def test_failed_connection_releases_task_group_and_can_reconnect(monkeypatch, failure):
    """The SDK owns AnyIO task groups: failures must close them in their entering task."""
    fail = True
    holder_tasks = []
    worker_tasks = []
    released = []
    workers_released = []

    async def worker(started):
        task = asyncio.current_task()
        worker_tasks.append(task)
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            # Transports need asynchronous cleanup even while their task group is cancelled.
            with anyio.CancelScope(shield=True):
                await checkpoint()
                workers_released.append(task)

    class Client:
        def __init__(self, connections):
            pass

        @asynccontextmanager
        async def session(self, name):
            owner = asyncio.current_task()
            holder_tasks.append(owner)
            try:
                async with anyio.create_task_group() as group:
                    try:
                        started = asyncio.Event()
                        group.start_soon(worker, started)
                        await started.wait()
                        if fail and failure == "session_timeout":
                            await asyncio.Event().wait()
                        yield object()
                    finally:
                        group.cancel_scope.cancel()
            finally:
                assert asyncio.current_task() is owner
                released.append(owner)

    async def echo(value: str) -> str:
        return value

    async def load_tools(session):
        if fail:
            if failure == "tools_error":
                raise RuntimeError("tool discovery failed")
            await asyncio.Event().wait()
        return [StructuredTool.from_function(coroutine=echo, name="echo", description="Echo.")]

    monkeypatch.setattr("openbot.mcp.manager.MultiServerMCPClient", Client)
    monkeypatch.setattr("openbot.mcp.manager.load_mcp_tools", load_tools)
    registry = ToolRegistry()
    manager = McpManager(
        servers=[McpServerConfig(name="remote", transport="http", url="https://example.invalid/mcp",
                                 headers={"Authorization": "Bearer test"})],
        registry=registry, settings=SimpleNamespace(tool_output_cap=400), storage=None,
        connect_timeout=0.1,
    )
    try:
        status = await asyncio.wait_for(manager.connect("remote"), 1)
        assert status.status == "error"
        assert ("RuntimeError: tool discovery failed" if failure == "tools_error"
                else "TimeoutError") in status.error
        assert not manager.interactive("remote")
        assert released == holder_tasks
        assert workers_released == worker_tasks
        assert all(task.done() for task in [*holder_tasks, *worker_tasks])
        assert not manager._sessions
        assert registry.specs() == []

        fail = False
        status = await asyncio.wait_for(manager.connect("remote"), 1)
        assert status.status == "connected"
        assert status.error is None
        assert status.tools == ["remote__echo"]
        assert await registry.get("remote__echo").ainvoke({"value": "ready"}) == "ready"
        await asyncio.wait_for(manager.stop(), 1)
        assert manager.status("remote").status == "disconnected"
        assert released == holder_tasks
        assert workers_released == worker_tasks
        assert all(task.done() for task in [*holder_tasks, *worker_tasks])
        assert registry.specs() == []
    finally:
        for task in holder_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*holder_tasks, return_exceptions=True)
