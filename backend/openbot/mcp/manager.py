"""Connects configured MCP servers and registers their tools alongside the built-ins.

One long-lived session per server (a stdio child process or a streamable-HTTP session) for the life
of the process; tools are renamed `<server>__<tool>`, wrapped so their output honours the tool
output cap like every other tool, and registered with source `mcp:<server>`. Failures are recorded
per server and never stop the others or the boot.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp.client.stdio import get_default_environment

from openbot.mcp.config import McpServerConfig
from openbot.mcp.oauth import DbTokenStorage, PendingFlows, build_oauth_provider
from openbot.tools.builtin.workspace import cap

log = logging.getLogger(__name__)

OAUTH_FLOW_TIMEOUT = 300.0


@dataclass
class ServerStatus:
    name: str
    transport: str
    status: str                 # connected | connecting | authorizing | needs_auth | disconnected | error | disabled
    enabled: bool = True
    oauth: bool = False
    url: str | None = None
    error: str | None = None
    tools: list[str] = field(default_factory=list)


def _flatten(result: Any) -> str:
    """MCP tools return content blocks; the model (and the cap) want text."""
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        parts = []
        for block in result:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, dict):
                parts.append(str({k: v for k, v in block.items() if k != "id"}))
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(result)


def _wrap(tool: BaseTool, name: str, cap_chars: int) -> BaseTool:
    async def run(**kwargs: Any) -> str:
        result = await tool.ainvoke(kwargs)
        return cap(_flatten(result), cap_chars, hint="ask the tool for less, or page through results")

    return StructuredTool.from_function(coroutine=run, name=name, description=tool.description or name,
                                        args_schema=tool.args_schema)


class McpManager:
    def __init__(self, servers: list[McpServerConfig], registry, settings, storage: Callable[[str], DbTokenStorage] | None,
                 flows: PendingFlows | None = None, connect_timeout: float = 30.0) -> None:
        self._servers = {s.name: s for s in servers}
        self._registry = registry
        self._settings = settings
        self._storage = storage
        self.flows = flows or PendingFlows()
        self._connect_timeout = connect_timeout
        self._status: dict[str, ServerStatus] = {}
        self._sessions: dict[str, tuple[asyncio.Task, asyncio.Event]] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        for s in servers:
            st = ServerStatus(name=s.name, transport=s.transport, status="disconnected", enabled=s.enabled, oauth=s.oauth, url=s.url)
            if not s.enabled:
                st.status = "disabled"
            elif s.error:
                st.status, st.error = "error", s.error
            self._status[s.name] = st

    # --- queries -------------------------------------------------------------------------------------

    def status(self, name: str) -> ServerStatus:
        return self._status[name]

    def statuses(self) -> list[ServerStatus]:
        return list(self._status.values())

    def has(self, name: str) -> bool:
        return name in self._servers

    def _store(self, name: str) -> DbTokenStorage | None:
        return self._storage(name) if self._storage is not None else None

    # --- lifecycle -----------------------------------------------------------------------------------

    async def start(self) -> None:
        """Connect every enabled server concurrently. OAuth servers without stored credentials wait for the
        operator (status needs_auth) instead of holding the boot for a browser that is not there."""
        to_connect = []
        for cfg in self._servers.values():
            st = self._status[cfg.name]
            if st.status in ("disabled", "error"):
                continue
            store = self._store(cfg.name) if cfg.oauth else None
            if cfg.oauth and store is not None and await store.get_tokens() is None:
                st.status = "needs_auth"
                continue
            to_connect.append(cfg.name)
        await asyncio.gather(*(self.connect(n) for n in to_connect), return_exceptions=True)
        summary = ", ".join(f"{s.name}={s.status}({len(s.tools)} tools)" for s in self.statuses())
        if summary:
            log.info("MCP servers: %s", summary)

    def begin_connect(self, name: str) -> asyncio.Task:
        """Connect in the background (the API uses this so an OAuth flow can wait for the browser)."""
        if (t := self._tasks.get(name)) and not t.done():
            return t
        task = asyncio.create_task(self.connect(name), name=f"mcp-connect:{name}")
        self._tasks[name] = task
        return task

    async def connect(self, name: str) -> ServerStatus:
        cfg = self._servers[name]
        st = self._status[name]
        if not cfg.enabled or cfg.error:
            return st
        await self._close(name)
        st.status, st.error = "connecting", None
        timeout = OAUTH_FLOW_TIMEOUT + self._connect_timeout if cfg.oauth else self._connect_timeout
        try:
            await asyncio.wait_for(self._open(cfg, st), timeout)
        except asyncio.CancelledError:
            await self._close(name)
            st.status = "disconnected"
            raise
        except Exception as e:  # noqa: BLE001 - anything a transport or the OAuth flow raises becomes the server's status
            await self._close(name)
            msg = f"{type(e).__name__}: {e}"[:500]
            store = self._store(name) if cfg.oauth else None
            if cfg.oauth and store is not None and await store.get_tokens() is None:
                st.status, st.error = "needs_auth", msg if not isinstance(e, asyncio.TimeoutError) else None
            else:
                st.status, st.error = "error", msg
            log.warning("MCP server %s: %s", name, msg)
        finally:
            self.flows.cancel(name)
        return st

    async def _open(self, cfg: McpServerConfig, st: ServerStatus) -> None:
        if cfg.transport == "stdio":
            conn: dict = {"transport": "stdio", "command": cfg.command, "args": list(cfg.args),
                          "env": {**get_default_environment(), **cfg.env}}
            if cfg.cwd:
                conn["cwd"] = cfg.cwd
        else:
            conn = {"transport": "streamable_http", "url": cfg.url, "headers": dict(cfg.headers) or None}
            if cfg.oauth:
                store = self._store(cfg.name)
                if store is None:
                    raise RuntimeError("OAuth is required but no credential storage is configured")
                if await store.get_tokens() is None:
                    st.status = "authorizing"
                conn["auth"] = build_oauth_provider(cfg.url, self._settings.public_url, store, self.flows, cfg.name,
                                                    timeout=OAUTH_FLOW_TIMEOUT)
        client = MultiServerMCPClient({cfg.name: conn})
        # The session's context manager (anyio task groups and cancel scopes underneath) must be
        # entered and exited by the same task, and connect() runs in whichever task asked (startup,
        # an API request), while disconnect runs in another. So each server gets a task of its own
        # that holds the session open until told to stop.
        ready: asyncio.Future = asyncio.get_running_loop().create_future()
        stop = asyncio.Event()
        task = asyncio.create_task(self._hold_session(cfg.name, client, ready, stop), name=f"mcp-session:{cfg.name}")
        self._sessions[cfg.name] = (task, stop)
        session = await ready
        raw_tools = await load_mcp_tools(session)
        source = f"mcp:{cfg.name}"
        self._registry.unregister_source(source)
        names = []
        for t in raw_tools:
            full = f"{cfg.name}__{t.name}"
            self._registry.register(_wrap(t, full, int(self._settings.tool_output_cap)), source=source)
            names.append(full)
        st.tools, st.status, st.error = sorted(names), "connected", None
        log.info("MCP server %s connected with %d tools", cfg.name, len(names))

    async def _hold_session(self, name: str, client: MultiServerMCPClient, ready: asyncio.Future, stop: asyncio.Event) -> None:
        try:
            async with client.session(name) as session:
                ready.set_result(session)
                await stop.wait()
        except BaseException as e:
            if not ready.done():
                ready.set_exception(e if isinstance(e, Exception) else RuntimeError(f"session task ended: {type(e).__name__}"))
            elif not isinstance(e, asyncio.CancelledError):
                log.debug("MCP session %s ended with %s", name, e, exc_info=True)
            if isinstance(e, asyncio.CancelledError):
                raise

    async def _close(self, name: str) -> None:
        held = self._sessions.pop(name, None)
        self._registry.unregister_source(f"mcp:{name}")
        self._status[name].tools = []
        if held is not None:
            task, stop = held
            stop.set()
            try:
                await asyncio.wait_for(task, 10)
            except (TimeoutError, asyncio.CancelledError):
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            except Exception:                        # a dead child process is exactly why we are closing
                log.debug("closing MCP server %s raised", name, exc_info=True)

    async def disconnect(self, name: str) -> ServerStatus:
        if (t := self._tasks.pop(name, None)) and not t.done():
            t.cancel()
            await asyncio.gather(t, return_exceptions=True)
        await self._close(name)
        st = self._status[name]
        if st.status not in ("disabled",):
            st.status = "disconnected"
        return st

    async def forget_credentials(self, name: str) -> ServerStatus:
        await self.disconnect(name)
        store = self._store(name)
        if store is not None:
            await store.clear()
        st = self._status[name]
        if self._servers[name].oauth:
            st.status = "needs_auth"
        return st

    async def stop(self) -> None:
        for name in list(self._servers):
            await self.disconnect(name)
