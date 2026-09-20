"""Telegram channel webhook endpoint.

Provides a public webhook endpoint for Telegram to send updates to OpenBot.
The webhook receives updates, posts messages to threads, and returns 200.
Bot responses are delivered asynchronously via the TelegramDeliveryListener.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request, Response

from openbot.channels.telegram import (
    deliver_to_telegram,
    parse_telegram_update,
    process_telegram_message,
    validate_webhook_token,
)
from openbot.services import Services

log = logging.getLogger(__name__)

router = APIRouter(prefix="/channels/telegram", tags=["telegram"])


@router.post("/webhook")
async def telegram_webhook(request: Request):
    """Handle incoming Telegram webhook updates.

    Flow:
        1. Validate secret token (if a webhook secret is configured).
        2. Parse the Telegram update.
        3. For commands (/new, /start, /help): process synchronously and send the
           response immediately.
        4. For regular messages: post to the thread and return 200. The bot response
           is generated asynchronously and delivered by TelegramDeliveryListener.
    """
    services: Services = request.app.state.services
    if services is None:
        raise HTTPException(500, "Services not initialized")

    # --- Secret-token validation (Telegram sends the raw token, not HMAC) ---
    body = await request.body()
    secret = services.settings.telegram_webhook_secret
    if secret:
        token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not validate_webhook_token(secret, token):
            raise HTTPException(403, "Invalid webhook secret token")

    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, "Invalid JSON")

    update = parse_telegram_update(data)
    if update is None:
        # Return 200 to acknowledge the update even if we can't process it
        return Response(status_code=200)

    session_factory = services.session_factory

    # Process the update — returns a response text for commands, None for messages
    async with session_factory() as session:
        response_text = await process_telegram_message(services, session, update)

    # Commands produce an immediate response; regular messages have None here
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
