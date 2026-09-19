"""Telegram channel webhook endpoint.

Provides a public webhook endpoint for Telegram to send updates to OpenBot.
The webhook receives updates, processes them, and stores them in the thread system.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response

from openbot.channels.telegram import (
    deliver_to_telegram,
    handle_telegram_message,
    parse_telegram_update,
)
from openbot.services import Services

log = logging.getLogger(__name__)

router = APIRouter(prefix="/channels/telegram", tags=["telegram"])


@router.post("/webhook")
async def telegram_webhook(request: Request):
    """Handle incoming Telegram webhook updates."""
    # Parse the update
    try:
        data = await request.json()
    except ValueError:
        raise HTTPException(400, "Invalid JSON")
    
    update = parse_telegram_update(data)
    if update is None:
        # Return 200 to acknowledge the update even if we can't process it
        return Response(status_code=200)
    
    # Get services from app state
    services: Services = request.app.state.services
    if services is None:
        raise HTTPException(500, "Services not initialized")
    
    # Get session factory
    session_factory = services.session_factory
    
    # Process the update
    async with session_factory() as session:
        response_text = await handle_telegram_message(services, session, update)
    
    # Send response to Telegram
    if response_text and update.chat_id:
        await deliver_to_telegram(services, update.chat_id, response_text)
    
    return Response(status_code=200)


@router.post("/webhook/test")
async def telegram_webhook_test(request: Request):
    """Test endpoint to verify webhook is working."""
    return {"status": "ok", "message": "Telegram webhook is active"}


@router.get("/status")
async def telegram_status(request: Request):
    """Get Telegram channel status."""
    services: Services = request.app.state.services
    if services is None:
        raise HTTPException(500, "Services not initialized")
    
    return {
        "configured": services.settings.telegram_bot_token is not None,
        "webhook_url": services.settings.telegram_webhook_url,
        "webhook_secret": services.settings.telegram_webhook_secret is not None,
    }