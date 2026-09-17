from __future__ import annotations

import asyncio
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from openbot.api.deps import get_services, get_session
from openbot.api.schemas import McpConnectOut, McpServerCreate, McpServerOut
from openbot.db.models import McpServer
from openbot.mcp import server_from_row
from openbot.services import Services

router = APIRouter(prefix="/mcp", tags=["mcp"])

AUTH_URL_WAIT = 15.0     # how long connect waits for the OAuth flow to produce an authorization URL


def _mgr(services: Services):
    if services.mcp is None:
        raise HTTPException(503, "MCP is not initialised")
    return services.mcp


def _out(mgr, st) -> McpServerOut:
    return McpServerOut(**asdict(st), authorization_url=mgr.flows.authorization_url(st.name))


@router.get("/servers", response_model=list[McpServerOut])
async def list_servers(services: Services = Depends(get_services)):
    mgr = _mgr(services)
    return [_out(mgr, s) for s in mgr.statuses()]


@router.post("/servers", response_model=McpServerOut, status_code=201)
async def add_server(body: McpServerCreate, session: AsyncSession = Depends(get_session),
                     services: Services = Depends(get_services)):
    """Add a remote server from Settings. It is stored, then connected in the background; if it needs
    the operator's authorization, `authorization_url` appears on the listing for the UI to open."""
    mgr = _mgr(services)
    if mgr.has(body.name) or await session.get(McpServer, body.name) is not None:
        raise HTTPException(409, f"an MCP server named {body.name!r} already exists")
    row = McpServer(name=body.name, url=body.url)
    session.add(row)
    await session.commit()
    st = await mgr.add_server(server_from_row(row), connect=False)
    mgr.begin_connect(body.name)
    await asyncio.sleep(0)                      # let the connect task publish "connecting"
    return _out(mgr, mgr.status(body.name) if mgr.has(body.name) else st)


@router.delete("/servers/{name}", status_code=204)
async def remove_server(name: str, session: AsyncSession = Depends(get_session), services: Services = Depends(get_services)):
    """Remove a server that was added from Settings (servers from mcp.json are edited in the file)."""
    mgr = _mgr(services)
    if not mgr.has(name):
        raise HTTPException(404, "unknown MCP server")
    if mgr.status(name).source != "db":
        raise HTTPException(409, f"{name} comes from the config file; remove it there")
    await mgr.remove_server(name)
    row = await session.get(McpServer, name)
    if row is not None:
        await session.delete(row)
        await session.commit()
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
        raise HTTPException(409, "server is disabled in the config file")
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
    return _out(mgr, await mgr.disconnect(name))


@router.delete("/servers/{name}/credentials", response_model=McpServerOut)
async def forget_credentials(name: str, services: Services = Depends(get_services)):
    """Forget the stored OAuth tokens; the server goes back to needs_auth until connected again."""
    mgr = _mgr(services)
    if not mgr.has(name):
        raise HTTPException(404, "unknown MCP server")
    return _out(mgr, await mgr.forget_credentials(name))
