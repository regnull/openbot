"""Slack channel Events API endpoint (webhook transport).

Socket Mode (the default transport) needs no endpoint at all; this webhook is
for deployments that prefer Slack's Events API. Bot responses are delivered
asynchronously via the SlackDeliveryListener either way.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from openbot.api.deps import get_services
from openbot.channels.slack import (
    deliver_to_slack,
    parse_slack_event,
    process_slack_message,
    validate_slack_signature,
)
from openbot.services import Services

log = logging.getLogger(__name__)

router = APIRouter(prefix="/channels/slack", tags=["slack"])


@router.post("/events")
async def slack_events(request: Request, services: Services = Depends(get_services)):
    """Handle incoming Slack Events API payloads.

    Flow:
        1. Validate the Slack request signature (if a signing secret is configured).
        2. Answer url_verification challenges.
        3. For commands (/new, /start, /help): process synchronously and post the
           response immediately.
        4. For regular messages: post to the thread and return 200. The bot response
           is generated asynchronously and delivered by SlackDeliveryListener.
    """
    body = await request.body()
    secret = services.settings.slack_signing_secret
    if secret:
        signature = request.headers.get("X-Slack-Signature", "")
        timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
        if not validate_slack_signature(secret, timestamp, body, signature):
            raise HTTPException(403, "Invalid Slack request signature")

    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, "Invalid JSON")

    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    # Slack retries unacknowledged events; app-level dedup is out of scope for v1.
    if payload.get("type") != "event_callback":
        return Response(status_code=200)

    event = parse_slack_event(payload.get("event") or {})
    if event is None:
        return Response(status_code=200)
    # Only the original post starts a run (see channels/slack.py): an edited or
    # replied-to message is re-announced with ts != event_ts.
    raw = payload.get("event") or {}
    if raw.get("ts") != raw.get("event_ts"):
        return Response(status_code=200)

    session_factory = services.session_factory

    # Process the event — returns a response text for commands, None for messages
    async with session_factory() as session:
        response_text = await process_slack_message(services, session, event)
        await session.commit()

    # Commands produce an immediate response; regular messages have None here
    if response_text and event.channel_id:
        await deliver_to_slack(services, event.channel_id, response_text)

    return Response(status_code=200)


@router.get("/status")
async def slack_status(services: Services = Depends(get_services)):
    """Get Slack channel status."""
    return {
        "configured": services.settings.slack_bot_token is not None,
        "transport": services.settings.slack_transport,
        "socket_mode": services.settings.slack_app_token is not None,
        "signing_secret": services.settings.slack_signing_secret is not None,
        "socket_running": getattr(services, "_slack_socket", None) is not None
            and getattr(services._slack_socket, "_running", False),
    }
