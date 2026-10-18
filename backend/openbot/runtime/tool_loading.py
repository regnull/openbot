"""Lazy MCP tools: bound to the agent, but sent to the model only once the bot asks for them.

Every model call re-sends the definition of every bound tool. An MCP server can bring dozens of
tools with long schemas (Linear: 76 tools, ~30k tokens), so a bot carrying one paid that on every
call of every run while using it a handful of times a week. Here a run's MCP tools are bound as
usual (so the tool node can execute them) but left out of each model request until the bot loads
them with `load_tools`; the system prompt lists their names so the bot knows what it can load.

The loaded set lives in the agent state, so it survives summarization and context clearing and
lasts for the rest of the run. Loaded tools go at the end of the request's tool list, after the
always-on ones, so a load leaves the cached prefix of earlier tool definitions intact.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, NotRequired

from langchain.agents.middleware import AgentMiddleware, AgentState, ModelRequest, ToolCallRequest
from langchain.agents.middleware.types import OmitFromInput
from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.types import Command
from pydantic import BaseModel, Field

LOAD_TOOLS = "load_tools"
MAX_LOAD_PER_CALL = 15  # one call loading every Linear tool would put the whole cost right back
MAX_QUERY_MATCHES = 5
DESCRIPTION_PREVIEW = 200  # chars of each loaded tool's description echoed back in the result


def _union(current: list[str] | None, new: list[str] | None) -> list[str]:
    merged = list(current or [])
    merged += [n for n in (new or []) if n not in merged]
    return merged


class DeferredToolsState(AgentState):
    # The reducer must come last in the metadata: langgraph only looks at the final item.
    loaded_tools: Annotated[NotRequired[list[str]], OmitFromInput, _union]


LOAD_TOOLS_DESCRIPTION = """\
Load tools listed under "Tools to load on demand" in your system prompt, so you can call them.
Their definitions are left out of your context until loaded, to save tokens. A loaded tool stays
available for the rest of this run.

- `names`: exact tool names to load, e.g. ["linear__get_issue", "linear__save_comment"].
- `query`: keywords to search the loadable tools' names and descriptions when you do not know the
  exact name, e.g. "comment on an issue"; the best matches are loaded.

Load only what the task needs, at most 15 per call. You can call the loaded tools from your next
step on."""


class LoadToolsInput(BaseModel):
    names: list[str] = Field(default_factory=list, description="Exact names of the tools to load.")
    query: str = Field(default="", description="Keywords to find tools by name and description.")


def _words(text: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", text.lower()) if len(w) > 1}


def search_tools(deferred: dict[str, BaseTool], query: str, limit: int = MAX_QUERY_MATCHES) -> list[str]:
    """The deferred tools that best match `query`: a word in the name counts double one in the
    description. Ties keep the server's own order."""
    words = _words(query)
    if not words:
        return []
    scored = []
    for i, (name, tool) in enumerate(deferred.items()):
        score = 2 * len(words & _words(name)) + len(words & _words(tool.description or ""))
        if score:
            scored.append((-score, i, name))
    return [name for _score, _i, name in sorted(scored)[:limit]]


def resolve_names(deferred: dict[str, BaseTool], names: list[str]) -> tuple[list[str], list[str]]:
    """(found, unknown). A name without its server prefix is accepted when exactly one server has it."""
    found, unknown = [], []
    for raw in names:
        name = raw.strip()
        if name in deferred:
            found.append(name)
            continue
        suffix = [n for n in deferred if n.split("__", 1)[-1] == name]
        if len(suffix) == 1:
            found.append(suffix[0])
        else:
            unknown.append(name)
    return list(dict.fromkeys(found)), unknown


def _preview(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= DESCRIPTION_PREVIEW else text[:DESCRIPTION_PREVIEW] + "…"


def deferred_tools_section(names: list[str]) -> str:
    """The prompt section listing loadable tools by server, names only (definitions cost tokens)."""
    by_server: dict[str, list[str]] = {}
    for name in names:
        server, _, short = name.partition("__")
        by_server.setdefault(server if short else "other", []).append(short or name)
    lines = "\n".join(f"- {server}: {', '.join(tools)}" for server, tools in by_server.items())
    return (
        "# Tools to load on demand\n"
        "These tools are available to you, but their definitions are not loaded, to save context. "
        "Before calling one, load it with load_tools (full name is `<server>__<tool>`, e.g. "
        f"`{names[0]}`), or find it with load_tools(query=...). Loaded tools stay available for "
        f"the rest of the run.\n{lines}"
    )


class DeferredToolsMiddleware(AgentMiddleware):
    """Keeps `deferred` tools out of model requests until the bot loads them with `load_tools`."""

    state_schema = DeferredToolsState

    def __init__(self, deferred: list[BaseTool]) -> None:
        super().__init__()
        self.deferred = {t.name: t for t in deferred}
        self.tools = [
            StructuredTool.from_function(
                name=LOAD_TOOLS,
                description=LOAD_TOOLS_DESCRIPTION,
                func=self._load,
                coroutine=self._aload,
                args_schema=LoadToolsInput,
                infer_schema=False,
            )
        ]

    # --- the load_tools tool ---------------------------------------------------------------------

    def _load(self, runtime: ToolRuntime, names: list[str] | None = None, query: str = "") -> Command:
        found, unknown = resolve_names(self.deferred, names or [])
        matched = [n for n in search_tools(self.deferred, query) if n not in found] if query else []
        wanted = (found + matched)[:MAX_LOAD_PER_CALL]
        already = set((runtime.state or {}).get("loaded_tools") or [])
        lines = []
        if wanted:
            lines.append("Loaded — call them from your next step on:")
            lines += [
                f"- {n}{' (already loaded)' if n in already else ''}: {_preview(self.deferred[n].description)}"
                for n in wanted
            ]
        skipped = (found + matched)[MAX_LOAD_PER_CALL:]
        if skipped:
            lines.append(f"Not loaded (over {MAX_LOAD_PER_CALL} per call): {', '.join(skipped)}.")
        if unknown:
            lines.append(
                f"Unknown: {', '.join(unknown)}. Use a name from \"Tools to load on demand\" in your "
                "system prompt, or load_tools(query=...)."
            )
        if query and not matched and not found:
            lines.append(f"No loadable tool matches {query!r}.")
        if not lines:
            lines.append("Nothing to load: pass `names` or `query`.")
        status = "success" if wanted else "error"
        content = "\n".join(lines)
        if status == "error":
            content = f"error: {content}"
        message = ToolMessage(content, tool_call_id=runtime.tool_call_id, name=LOAD_TOOLS, status=status)
        return Command(update={"loaded_tools": wanted, "messages": [message]})

    async def _aload(self, runtime: ToolRuntime, names: list[str] | None = None, query: str = "") -> Command:
        return self._load(runtime, names, query)

    # --- request filtering -----------------------------------------------------------------------

    def _visible(self, request: ModelRequest) -> ModelRequest:
        loaded = [n for n in (request.state or {}).get("loaded_tools") or [] if n in self.deferred]
        keep = [t for t in request.tools if isinstance(t, dict) or t.name not in self.deferred]
        return request.override(tools=[*keep, *(self.deferred[n] for n in loaded)])

    def wrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Any]) -> Any:
        return handler(self._visible(request))

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[Any]]
    ) -> Any:
        return await handler(self._visible(request))

    # --- calls to a tool that was never loaded ---------------------------------------------------

    def _unloaded(self, request: ToolCallRequest) -> Command | None:
        """The model knows deferred names from the prompt and sometimes calls one without loading it,
        guessing its arguments. Refuse that call, but load the tool, so the retry has its schema."""
        name = request.tool_call["name"]
        if name not in self.deferred or name in ((request.state or {}).get("loaded_tools") or []):
            return None
        message = ToolMessage(
            f"error: {name} was not loaded, so this call did not run. It is loaded now: call it again "
            f"from your next step, using its definition. Description: {_preview(self.deferred[name].description)}",
            tool_call_id=request.tool_call["id"],
            name=name,
            status="error",
        )
        return Command(update={"loaded_tools": [name], "messages": [message]})

    def wrap_tool_call(self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], Any]) -> Any:
        return self._unloaded(request) or handler(request)

    async def awrap_tool_call(
        self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], Awaitable[Any]]
    ) -> Any:
        return self._unloaded(request) or await handler(request)
