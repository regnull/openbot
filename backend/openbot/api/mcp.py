from __future__ import annotations

import asyncio
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from openbot.api.deps import get_services
from openbot.api.schemas import McpConnectOut, McpServerOut
from openbot.services import Services

router = APIRouter(prefix="/mcp", tags=["mcp"])

AUTH_URL_WAIT = 15.0     # how long connect waits for the OAuth flow to produce an authorization URL


def _mgr(services: Services):
    if services.mcp is None:
        raise HTTPException(503, "MCP is not initialised")
    return services.mcp


@router.get("/servers", response_model=list[McpServerOut])
async def list_servers(services: Services = Depends(get_services)):
    return [McpServerOut(**asdict(s)) for s in _mgr(services).statuses()]


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
    while asyncio.get_running_loop().time() < deadline:
        if task.done():
            break
        if (url := mgr.flows.authorization_url(name)) is not None:
            return McpConnectOut(status="authorizing", authorization_url=url)
        await asyncio.sleep(0.05)
    if task.done():
        return McpConnectOut(status=mgr.status(name).status)
    if (url := mgr.flows.authorization_url(name)) is not None:
        return McpConnectOut(status="authorizing", authorization_url=url)
    return McpConnectOut(status=mgr.status(name).status)


@router.post("/servers/{name}/disconnect", response_model=McpServerOut)
async def disconnect_server(name: str, services: Services = Depends(get_services)):
    mgr = _mgr(services)
    if not mgr.has(name):
        raise HTTPException(404, "unknown MCP server")
    return McpServerOut(**asdict(await mgr.disconnect(name)))


@router.delete("/servers/{name}/credentials", response_model=McpServerOut)
async def forget_credentials(name: str, services: Services = Depends(get_services)):
    """Forget the stored OAuth tokens; the server goes back to needs_auth until connected again."""
    mgr = _mgr(services)
    if not mgr.has(name):
        raise HTTPException(404, "unknown MCP server")
    return McpServerOut(**asdict(await mgr.forget_credentials(name)))
