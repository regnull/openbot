"""Connects configured MCP servers and registers their tools alongside the built-ins.

One long-lived session per server (a stdio child process or a streamable-HTTP session) for the life
of the process; tools are renamed `<server>__<tool>`, wrapped so their output honours the tool
output cap like every other tool, and registered with source `mcp:<server>`. Failures are recorded
per server and never stop the others or the boot.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp.client.stdio import get_default_environment

from openbot.mcp.config import McpServerConfig
from openbot.mcp.oauth import (
    AuthorizationRequired,
    DbTokenStorage,
    PendingFlows,
    build_oauth_provider,
)
from openbot.tools.builtin.workspace import cap

log = logging.getLogger(__name__)

OAUTH_FLOW_TIMEOUT = 300.0
MAX_TOOL_NAME = 64                      # OpenAI-compatible providers reject longer function names
_NAME_BAD = re.compile(r"[^a-zA-Z0-9_-]")


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
    source: str = "file"        # "file" (mcp.json) | "db" (added from Settings; removable there)


def tool_name(server: str, name: str) -> str:
    """`<server>__<tool>`, fitted to provider function-name rules (`^[a-zA-Z0-9_-]{1,64}$`)."""
    return f"{server}__{_NAME_BAD.sub('_', name)}"[:MAX_TOOL_NAME]


def _flatten(content: Any) -> str:
    """MCP tools return content blocks; the model (and the cap) want text. Binary blocks become a
    placeholder rather than kilobytes of base64 the model cannot use."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                parts.append(str(block))
            elif block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            else:
                mime = block.get("mime_type") or block.get("mimeType") or block.get("type", "content")
                parts.append(f"[{mime} content omitted]")
        return "\n".join(parts)
    return str(content)


def _wrap(tool: BaseTool, name: str, cap_chars: int) -> BaseTool:
    """The registered face of an MCP tool: same schema, capped text output, and every failure (the
    server's isError, a dead transport, a lapsed authorization) returned as an "error: ..." result
    the model can react to, instead of an exception that fails the whole run."""

    async def run(**kwargs: Any) -> str:
        try:
            # Invoking with a tool call (not a bare dict) yields a ToolMessage, which is the only place
            # the adapter surfaces the server's isError status.
            msg = await tool.ainvoke({"name": tool.name, "args": kwargs, "id": "mcp", "type": "tool_call"})
        except Exception as e:  # noqa: BLE001 - see docstring
            return cap(f"error: {type(e).__name__}: {e}", cap_chars)
        text = _flatten(msg.content if isinstance(msg, ToolMessage) else msg)
        if isinstance(msg, ToolMessage) and msg.status == "error":
            text = f"error: {text}"
        return cap(text, cap_chars, hint="ask the tool for less, or page through results")

    return StructuredTool.from_function(coroutine=run, name=name, description=tool.description or name,
                                        args_schema=tool.args_schema)


class McpManager:
    def __init__(self, servers: list[McpServerConfig], registry, settings,
                 storage: Callable[..., DbTokenStorage] | None, flows: PendingFlows | None = None,
                 connect_timeout: float = 30.0, store=None) -> None:
        self._servers = {s.name: s for s in servers}
        self._registry = registry
        self._settings = settings
        self._storage = storage
        self.store = store          # McpServerStore; the API reads/writes specs through it
        self.init_error: str | None = None   # set when the store could not be built (bad credential key)
        self.flows = flows or PendingFlows()
        self._connect_timeout = connect_timeout
        self._status: dict[str, ServerStatus] = {}
        self._sessions: dict[str, tuple[asyncio.Task, asyncio.Event]] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._interactive: dict[str, bool] = {}
        for s in servers:
            self._register(s)

    def _register(self, s: McpServerConfig) -> ServerStatus:
        st = ServerStatus(name=s.name, transport=s.transport, status="disconnected", enabled=s.enabled, oauth=s.oauth,
                          url=s.url, source=s.source)
        if not s.enabled:
            st.status = "disabled"
        elif s.error:
            st.status, st.error = "error", s.error
        self._servers[s.name] = s
        self._status[s.name] = st
        return st

    async def add_server(self, cfg: McpServerConfig, connect: bool = True) -> ServerStatus:
        """Add a server at runtime (from the Settings UI). With `connect`, connect it now, interactively:
        the caller is an operator who can open the authorization page."""
        if cfg.name in self._servers:
            raise ValueError(f"MCP server {cfg.name} already exists")
        st = self._register(cfg)
        if connect and st.status not in ("disabled", "error"):
            await self.connect(cfg.name, interactive=True)
        return st

    async def update_server(self, cfg: McpServerConfig) -> ServerStatus:
        """Replace a server's spec (edited in Settings): reconnect if enabled, otherwise stop it."""
        if (t := self._tasks.pop(cfg.name, None)) and not t.done():
            t.cancel()
            await asyncio.gather(t, return_exceptions=True)
        await self._close(cfg.name)
        st = self._register(cfg)
        if st.status not in ("disabled", "error"):
            # In the background and non-interactively: a PATCH must return at once, not wait out a
            # 30s transport timeout or minutes for a browser. An OAuth server without credentials
            # lands in needs_auth and the UI offers "Connect & authorize".
            st.status = "connecting"
            task = asyncio.create_task(self.connect(cfg.name), name=f"mcp-connect:{cfg.name}")
            self._tasks[cfg.name] = task
        return st

    async def remove_server(self, name: str) -> None:
        """Disconnect, forget its credentials, and drop it from the manager."""
        if name not in self._servers:
            return
        await self.forget_credentials(name)
        self._servers.pop(name, None)
        self._status.pop(name, None)
        self._interactive.pop(name, None)

    # --- queries -------------------------------------------------------------------------------------

    def status(self, name: str) -> ServerStatus:
        return self._status[name]

    def statuses(self) -> list[ServerStatus]:
        return list(self._status.values())

    def has(self, name: str) -> bool:
        return name in self._servers

    def interactive(self, name: str) -> bool:
        """True only while an operator-initiated connect is running: the one time the OAuth flow may
        wait for a browser. At boot, on reconnect, and during a bot's tool call it must fail fast."""
        return self._interactive.get(name, False)

    def _store(self, name: str) -> DbTokenStorage | None:
        if self._storage is None:
            return None
        return self._storage(name, self._servers[name].url)

    async def _stored_tokens(self, name: str):
        store = self._store(name)
        return None if store is None else await store.get_tokens()

    # --- lifecycle -----------------------------------------------------------------------------------

    async def start(self) -> None:
        """Connect every enabled server concurrently, never interactively: OAuth servers without usable
        credentials wait for the operator (needs_auth) instead of holding the boot for a browser."""
        to_connect = []
        for cfg in self._servers.values():
            st = self._status[cfg.name]
            if st.status in ("disabled", "error"):
                continue
            if cfg.oauth:
                try:
                    if await self._stored_tokens(cfg.name) is None:
                        st.status = "needs_auth"
                        continue
                except Exception as e:  # noqa: BLE001 - a bad key or corrupt row must not take the boot down
                    st.status, st.error = "error", f"credential storage: {type(e).__name__}: {e}"[:500]
                    log.warning("MCP server %s: %s", cfg.name, st.error)
                    continue
            to_connect.append(cfg.name)
        await asyncio.gather(*(self.connect(n) for n in to_connect), return_exceptions=True)
        summary = ", ".join(f"{s.name}={s.status}({len(s.tools)} tools)" for s in self.statuses())
        if summary:
            log.info("MCP servers: %s", summary)

    def begin_connect(self, name: str) -> asyncio.Task:
        """Operator-initiated connect in the background; the API reads the authorization URL from `flows`."""
        if (t := self._tasks.get(name)) and not t.done():
            return t
        task = asyncio.create_task(self.connect(name, interactive=True), name=f"mcp-connect:{name}")
        self._tasks[name] = task
        return task

    async def connect(self, name: str, interactive: bool = False) -> ServerStatus:
        cfg = self._servers[name]
        st = self._status[name]
        if not cfg.enabled or cfg.error:
            return st
        st.status, st.error = "connecting", None
        self._interactive[name] = interactive
        timeout = OAUTH_FLOW_TIMEOUT + self._connect_timeout if (cfg.oauth and interactive) else self._connect_timeout
        try:
            await asyncio.wait_for(self._open(cfg, st), timeout)
        except asyncio.CancelledError:
            await self._close(name)
            st.status = "disconnected"
            raise
        except AuthorizationRequired:
            await self._close(name)
            st.status, st.error = "needs_auth", None
        except Exception as e:  # noqa: BLE001 - anything a transport or the OAuth flow raises becomes the server's status
            await self._close(name)
            msg = f"{type(e).__name__}: {e}"[:500]
            if cfg.oauth and (interactive or await self._safe_no_tokens(name)):
                st.status, st.error = "needs_auth", None if isinstance(e, asyncio.TimeoutError) else msg
            else:
                st.status, st.error = "error", msg
            log.warning("MCP server %s: %s", name, msg)
        finally:
            self._interactive[name] = False
            self.flows.cancel(name)
        return st

    async def _safe_no_tokens(self, name: str) -> bool:
        try:
            return await self._stored_tokens(name) is None
        except Exception:  # noqa: BLE001
            return False

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
                                                    allow=lambda: self.interactive(cfg.name), timeout=OAUTH_FLOW_TIMEOUT)
        await self._start_session(cfg.name, MultiServerMCPClient({cfg.name: conn}), None)

    async def _start_session(self, name: str, client, tools: list[BaseTool] | None) -> None:
        """Open a session in its own task, load and register its tools, then retire the previous
        session. The old tools stay registered until the new ones replace them, so a reconnect never
        leaves a window in which runs cannot find the server's tools."""
        # The session's context manager (anyio task groups and cancel scopes underneath) must be
        # entered and exited by the same task, and connect() runs in whichever task asked (startup,
        # an API request), while disconnect runs in another. Hence one holder task per session.
        ready: asyncio.Future = asyncio.get_running_loop().create_future()
        stop = asyncio.Event()
        task = asyncio.create_task(self._hold_session(name, client, ready, stop), name=f"mcp-session:{name}")
        try:
            session = await ready
            raw_tools = tools if tools is not None else await load_mcp_tools(session)
        except BaseException:
            stop.set()
            await asyncio.gather(task, return_exceptions=True)
            raise
        previous = self._sessions.get(name)
        self._sessions[name] = (task, stop)
        source = f"mcp:{name}"
        self._registry.unregister_source(source)
        names = []
        for t in raw_tools:
            full = tool_name(name, t.name)
            self._registry.register(_wrap(t, full, int(self._settings.tool_output_cap)), source=source)
            names.append(full)
        st = self._status[name]
        st.tools, st.status, st.error = sorted(names), "connected", None
        if previous is not None:
            await self._retire(name, *previous)
        log.info("MCP server %s connected with %d tools", name, len(names))

    async def _hold_session(self, name: str, client, ready: asyncio.Future, stop: asyncio.Event) -> None:
        try:
            async with client.session(name) as session:
                ready.set_result(session)
                await stop.wait()
        except asyncio.CancelledError:
            raise
        except BaseException as e:  # noqa: BLE001 - classified below: startup failure vs. a session dying later
            if not ready.done():
                ready.set_exception(e if isinstance(e, Exception) else RuntimeError(f"session task ended: {type(e).__name__}"))
                return
            if not stop.is_set():
                self._session_lost(name, e)

    def _session_lost(self, name: str, exc: BaseException) -> None:
        """A live session ended on its own (child process died, connection dropped). Say so, and stop
        advertising tools that would fail every call."""
        held = self._sessions.get(name)
        if held is None or held[0] is not asyncio.current_task():
            return
        self._sessions.pop(name, None)
        self._registry.unregister_source(f"mcp:{name}")
        st = self._status[name]
        st.tools, st.status, st.error = [], "error", f"session ended: {type(exc).__name__}: {exc}"[:500]
        log.warning("MCP server %s: %s", name, st.error)

    async def _retire(self, name: str, task: asyncio.Task, stop: asyncio.Event) -> None:
        stop.set()
        try:
            await asyncio.wait_for(task, 10)
        except (TimeoutError, asyncio.CancelledError):
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        except Exception:                        # a dead child process is exactly why we are closing
            log.debug("closing MCP server %s raised", name, exc_info=True)

    async def _close(self, name: str) -> None:
        held = self._sessions.pop(name, None)
        self._registry.unregister_source(f"mcp:{name}")
        self._status[name].tools = []
        if held is not None:
            await self._retire(name, *held)

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
