"""Discord channel status endpoint.

OpenBot connects to Discord through the gateway websocket (channels/discord.py),
so there is no inbound webhook to mount; this router only exposes status for
health checks and the settings page.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from openbot.api.deps import get_services
from openbot.services import Services

log = logging.getLogger(__name__)

router = APIRouter(prefix="/channels/discord", tags=["discord"])


@router.get("/status")
async def discord_status(services: Services = Depends(get_services)):
    """Get Discord channel status."""
    return {
        "configured": services.settings.discord_bot_token is not None,
        "transport": "gateway",
        "gateway_running": getattr(services, "_discord_gateway", None) is not None
            and getattr(services._discord_gateway, "_running", False),
    }
