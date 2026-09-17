from __future__ import annotations

import asyncio
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Response

from openbot.api.deps import get_services
from openbot.api.schemas import McpConnectOut, McpServerCreate, McpServerOut, McpServerUpdate
from openbot.mcp.config import McpConfigError
from openbot.mcp.store import McpKeyError
from openbot.services import Services

router = APIRouter(prefix="/mcp", tags=["mcp"])

AUTH_URL_WAIT = 15.0     # how long connect waits for the OAuth flow to produce an authorization URL


def _mgr(services: Services):
    if services.mcp is None:
        raise HTTPException(503, "MCP is not initialised")
    if services.mcp.store is None:
        raise HTTPException(503, services.mcp.init_error or "MCP configuration unavailable (credential key)")
    return services.mcp


def _out(mgr, st, spec: dict) -> McpServerOut:
    fields = asdict(st)
    fields["url"] = spec.get("url")          # the stored form (may hold ${VAR}), which is what an edit must round-trip
    return McpServerOut(**fields, authorization_url=mgr.flows.authorization_url(st.name),
                        command=spec.get("command"), args=list(spec.get("args") or []), cwd=spec.get("cwd"),
                        env=dict(spec.get("env") or {}), headers=dict(spec.get("headers") or {}))


async def _one(mgr, name: str) -> McpServerOut:
    return _out(mgr, mgr.status(name), await mgr.store.get(name) or {})


@router.get("/servers", response_model=list[McpServerOut])
async def list_servers(services: Services = Depends(get_services)):
    mgr = _mgr(services)
    specs = await mgr.store.all_masked()
    return [_out(mgr, s, specs.get(s.name, {})) for s in mgr.statuses()]


@router.post("/servers", response_model=McpServerOut, status_code=201)
async def add_server(body: McpServerCreate, services: Services = Depends(get_services)):
    """Add a server (remote or local stdio) from Settings. It is stored, then connected in the background;
    if it needs the operator's authorization, `authorization_url` appears on the listing for the UI to open."""
    mgr = _mgr(services)
    if mgr.has(body.name) or await mgr.store.raw(body.name) is not None:
        raise HTTPException(409, f"an MCP server named {body.name!r} already exists")
    try:
        await mgr.store.upsert(body.model_dump())
    except McpKeyError as e:
        raise HTTPException(503, str(e)) from e
    except McpConfigError as e:
        raise HTTPException(422, str(e)) from e
    st = await mgr.add_server(await mgr.store.config(body.name), connect=False)
    if st.status not in ("disabled", "error"):
        mgr.begin_connect(body.name)
        await asyncio.sleep(0)                  # let the connect task publish "connecting"
    return await _one(mgr, body.name)


@router.patch("/servers/{name}", response_model=McpServerOut)
async def update_server(name: str, body: McpServerUpdate, services: Services = Depends(get_services)):
    """Edit a server. The connection is restarted with the new spec in the background (or stopped when disabled)."""
    mgr = _mgr(services)
    if not mgr.has(name):
        raise HTTPException(404, "unknown MCP server")
    try:
        await mgr.store.update(name, body.model_dump(exclude_unset=True))
    except KeyError as e:
        raise HTTPException(404, "unknown MCP server") from e
    except McpKeyError as e:
        raise HTTPException(503, str(e)) from e
    except McpConfigError as e:
        raise HTTPException(422, str(e)) from e
    await mgr.update_server(await mgr.store.config(name))
    return await _one(mgr, name)


@router.delete("/servers/{name}", status_code=204)
async def remove_server(name: str, services: Services = Depends(get_services)):
    """Remove a server: disconnect, forget its credentials, delete its spec."""
    mgr = _mgr(services)
    if not mgr.has(name):
        raise HTTPException(404, "unknown MCP server")
    await mgr.remove_server(name)
    await mgr.store.delete(name)
    return Response(status_code=204)


@router.post("/servers/{name}/connect", response_model=McpConnectOut)
async def connect_server(name: str, services: Services = Depends(get_services)):
    """Connect (or reconnect) a server. For a remote server that needs the operator's authorization the
    connection runs in the background and this returns the URL to open; the flow completes when the
    authorization server redirects the browser to the public callback."""
    mgr = _mgr(services)
    if not mgr.has(name):
        raise HTTPException(404, "unknown MCP server")
    st = mgr.status(name)
    if st.status == "disabled":
        raise HTTPException(409, "server is disabled; enable it first")
    if st.error and st.status == "error" and "environment variable" in st.error:
        raise HTTPException(409, st.error)
    task = mgr.begin_connect(name)
    deadline = asyncio.get_running_loop().time() + AUTH_URL_WAIT
    while asyncio.get_running_loop().time() < deadline and not task.done():
        if (url := mgr.flows.authorization_url(name)) is not None:
            return McpConnectOut(status="authorizing", authorization_url=url)
        await asyncio.sleep(0.05)
    return McpConnectOut(status=mgr.status(name).status, authorization_url=mgr.flows.authorization_url(name))


@router.post("/servers/{name}/disconnect", response_model=McpServerOut)
async def disconnect_server(name: str, services: Services = Depends(get_services)):
    mgr = _mgr(services)
    if not mgr.has(name):
        raise HTTPException(404, "unknown MCP server")
    await mgr.disconnect(name)
    return await _one(mgr, name)


@router.delete("/servers/{name}/credentials", response_model=McpServerOut)
async def forget_credentials(name: str, services: Services = Depends(get_services)):
    """Forget the stored OAuth tokens; the server goes back to needs_auth until connected again."""
    mgr = _mgr(services)
    if not mgr.has(name):
        raise HTTPException(404, "unknown MCP server")
    await mgr.forget_credentials(name)
    return await _one(mgr, name)
