"""Slack channel adapter for OpenBot.

Receives Slack DMs over Socket Mode (no public URL needed), maps each Slack
user to a persistent thread, and delivers bot replies via the Web API.

Transport:
    - ``socket_mode`` (default): An app-level websocket (Socket Mode) carries
      events; no HTTP endpoint or request signing is required. Needs an app
      with Socket Mode enabled, a bot token (xoxb-) and an app-level token
      (xapp-) with the connections:write scope.
    - ``webhook``: Events API endpoint with Slack request-signature
      validation; set SLACK_SIGNING_SECRET and point Slack's Interactivity &
      Events URL at https://your-domain/api/v1/channels/slack/events.

Usage (socket mode):
    1. Create a Slack app at https://api.slack.com/apps (Socket Mode on,
       bot scopes: chat:write, im:history, im:read; event: message.im) and
       add an app-level token with connections:write.
    2. Set SLACK_BOT_TOKEN and SLACK_APP_TOKEN in your .env file (or the
       settings page).
    3. The adapter opens Socket Mode automatically on server startup.

Thread mapping:
    - Each Slack DM channel gets exactly one active thread
      (external_ref = "slack:{channel_id}").
    - The thread persists until the user issues /new, which creates a fresh thread.
    - Thread history is never merged across different Slack DM channels.

Delivery flow:
    - Event received (Socket Mode or Events API) -> posted to thread asynchronously.
    - The ActorSystem processes the message asynchronously (bot generates response).
    - A background SlackDeliveryListener subscribes to the EventBus, detects bot
      messages in Slack threads, and delivers them via chat.postMessage.

Slack re-announces a message when it is edited or replied to in-thread; only
``event_ts == ts`` events (the original post) are processed, so the bot never
answers its own answer twice.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
import time
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openbot.db.models import Actor, ExternalProfile, Thread
from openbot.runtime.delivery import create_thread, post_message
from openbot.services import Services

log = logging.getLogger(__name__)

SLACK_PREFIX = "slack:"
SLACK_THREAD_KIND = "chat"

SLACK_API_BASE = "https://slack.com/api"


@dataclass
class SlackEvent:
    """Parsed Slack message event."""
    event_id: str | None
    channel_id: str
    user_id: str
    text: str
    is_command: bool = False
    command: str | None = None


def parse_slack_event(event: dict) -> SlackEvent | None:
    """Parse a raw Slack message event into our internal representation.

    Only DMs (channel ids starting with ``D``) are accepted; channel messages
    are ignored so the bot never answers in shared channels. Bot and
    thread_broadcast echoes are dropped for the same reason: the reply loop.
    """
    if event.get("type") != "message":
        return None
    if event.get("bot_id") or event.get("subtype"):
        # bot_id: our own posts. subtype (thread_broadcast, message_changed,
        # ...): an edit or a reply to an answered message -- answering those is
        # how a bot ends up talking to itself.
        return None

    channel_id = event.get("channel", "")
    if not channel_id.startswith("D"):
        return None

    text = event.get("text", "")
    user_id = event.get("user")
    if not text or not isinstance(text, str) or not user_id:
        return None

    is_command = text.startswith("/")
    command = None
    if is_command:
        match = re.match(r"^/(\w+)(?:\s+.*)?$", text)
        if match:
            command = match.group(1).lower()

    return SlackEvent(
        event_id=event.get("event_ts") or event.get("ts"),
        channel_id=channel_id,
        user_id=user_id,
        text=text,
        is_command=is_command,
        command=command,
    )


def validate_slack_signature(
    signing_secret: str, timestamp: str, body: bytes, signature: str
) -> bool:
    """Validate Slack's request signature (v0 scheme) with a constant-time compare.

    Slack signs ``v0:<timestamp>:<raw body>`` with the signing secret; reject
    timestamps older than five minutes so captured requests cannot be replayed.
    """
    if not timestamp or not signature.startswith("v0="):
        return False
    try:
        if abs(time.time() - float(timestamp)) > 60 * 5:
            return False
    except ValueError:
        return False
    base = f"v0:{timestamp}:{body.decode('utf-8', 'replace')}"
    digest = hmac.new(signing_secret.encode(), base.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"v0={digest}", signature)


async def get_or_create_slack_actor(
    session: AsyncSession, user_id: str, display_name: str | None = None
) -> Actor:
    """Get or create a Slack user actor."""
    handle = f"sl_{user_id}"
    actor = (
        await session.execute(select(Actor).where(Actor.handle == handle))
    ).scalar_one_or_none()
    if actor is None:
        actor = Actor(
            kind="external",
            handle=handle,
            name=display_name or f"Slack {user_id}",
            description=f"Slack user {user_id}",
            external=ExternalProfile(webhook_url=None, webhook_secret=None),
        )
        session.add(actor)
        await session.flush()
    elif display_name and actor.name != display_name:
        # Update name if changed
        actor.name = display_name
    return actor


async def get_or_create_thread(
    services: Services, session: AsyncSession, channel_id: str, actor: Actor
) -> Thread:
    """Get or create a thread for a Slack DM channel."""
    external_ref = f"{SLACK_PREFIX}{channel_id}"
    thread = (
        await session.execute(
            select(Thread).where(Thread.external_ref == external_ref)
        )
    ).scalar_one_or_none()

    if thread is None:
        thread = await create_thread(
            services,
            session,
            title=f"Slack {actor.name}",
            handles=[],
            created_by=actor,
            external_ref=external_ref,
            include_human=False,
            kind=SLACK_THREAD_KIND,
        )
    return thread


async def handle_slack_command(
    services: Services, session: AsyncSession, event: SlackEvent, actor: Actor
) -> str | None:
    """Handle a Slack command. Returns response text, or None for non-commands."""
    if not event.is_command:
        return None

    if event.command == "new":
        external_ref = f"{SLACK_PREFIX}{event.channel_id}"

        # Mark old thread as finished (keep history but remove external_ref so
        # new messages go to a fresh thread).
        old_thread = (
            await session.execute(
                select(Thread).where(Thread.external_ref == external_ref)
            )
        ).scalar_one_or_none()

        if old_thread is not None:
            old_thread.external_ref = None
            await session.flush()

        # Create new thread
        await create_thread(
            services,
            session,
            title=f"Slack {actor.name}",
            handles=[],
            created_by=actor,
            external_ref=external_ref,
            include_human=False,
            kind=SLACK_THREAD_KIND,
        )

        return "\u2728 New conversation started. I've forgotten our previous discussion."

    if event.command == "start":
        return "\U0001f44b Welcome! I'm your AI assistant. Send me a message to get started."

    if event.command == "help":
        return (
            "\U0001f4a1 Commands:\n"
            "/new - Start a new conversation\n"
            "/start - Welcome message\n"
            "/help - Show this help"
        )

    return f"\u2753 Unknown command: /{event.command}"


async def send_slack_message(services: Services, channel_id: str, text: str) -> dict | None:
    """Send a message to a Slack DM channel via chat.postMessage."""
    bot_token = services.settings.slack_bot_token
    if not bot_token:
        log.warning("Slack bot token not configured")
        return None

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{SLACK_API_BASE}/chat.postMessage",
                json={"channel": channel_id, "text": text},
                headers={"Authorization": f"Bearer {bot_token}"},
            )
            body = response.json()
            if response.status_code == 200 and body.get("ok"):
                return body
            log.error("Slack API error: %s - %s", response.status_code, body.get("error", body))
            return None
    except Exception:
        log.exception("Failed to send Slack message")
        return None


async def process_slack_message(
    services: Services, session: AsyncSession, event: SlackEvent
) -> str | None:
    """Process an incoming Slack DM event.

    For commands, returns a response text to send immediately.
    For regular messages, posts to the thread (triggering async bot processing)
    and returns None -- the response will be delivered by SlackDeliveryListener.
    """
    actor = await get_or_create_slack_actor(session, event.user_id)

    # Handle commands synchronously (they produce immediate responses)
    if event.is_command:
        return await handle_slack_command(services, session, event, actor)

    # Regular message: post to thread and let the bot process asynchronously
    thread = await get_or_create_thread(services, session, event.channel_id, actor)

    try:
        await post_message(
            services,
            session,
            thread_id=thread.id,
            sender=actor,
            content=event.text,
            to_handles=[],
        )
    except Exception:
        log.exception("Failed to post Slack message to thread %s", thread.id)
        return "\u274c Error processing message"

    # Return None -- the bot response will be delivered asynchronously
    return None


async def deliver_to_slack(services: Services, channel_id: str, text: str) -> bool:
    """Deliver a bot reply to Slack."""
    if not services.settings.slack_bot_token:
        return False
    result = await send_slack_message(services, channel_id, text)
    return result is not None


def _parse_channel_id_from_ref(external_ref: str | None) -> str | None:
    """Extract the DM channel id from a slack:* external_ref."""
    if external_ref and external_ref.startswith(SLACK_PREFIX):
        channel_id = external_ref[len(SLACK_PREFIX):]
        return channel_id or None
    return None


# ---------------------------------------------------------------------------
# Socket Mode transport (app-level websocket, no public URL)
# ---------------------------------------------------------------------------

_RECONNECT_BACKOFF_BASE: float = 2.0
_RECONNECT_BACKOFF_CAP: float = 60.0


class SlackSocketModeClient:
    """Opens Slack Socket Mode and feeds message.im events into the same
    processing pipeline used by the Events API transport.

    Lifecycle:
        - ``start()`` creates the background connection task.
        - ``stop()`` cancels it gracefully.

    Each frame is acknowledged with its envelope id (Socket Mode redelivers
    anything not acked). On any drop the client re-runs ``apps.connections.open``
    and reconnects with exponential back-off.
    """

    def __init__(self, services: Services) -> None:
        self._services = services
        self._task: asyncio.Task | None = None
        self._running = False
        self._ws: object | None = None  # the active connection; set by _connect (tests patch it)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="slack-socket-mode")
        log.info("Slack Socket Mode client started")

    async def stop(self) -> None:
        self._running = False
        if self._ws is not None:
            try:
                await self._ws.close()  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001 - a dead socket on shutdown changes nothing
                log.debug("Slack Socket Mode close failed: %s", exc)
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log.info("Slack Socket Mode client stopped")

    # -- internal -------------------------------------------------------------

    async def _loop(self) -> None:
        backoff = _RECONNECT_BACKOFF_BASE
        while self._running:
            try:
                await self._connect_and_read()
                backoff = _RECONNECT_BACKOFF_BASE
            except asyncio.CancelledError:
                raise  # propagate so stop() sees clean cancellation
            except Exception:
                log.exception("Slack Socket Mode error; reconnecting in %.1fs", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _RECONNECT_BACKOFF_CAP)

    async def _open_connection_url(self) -> str:
        app_token = self._services.settings.slack_app_token
        if not app_token:
            raise RuntimeError("SLACK_APP_TOKEN is required for Socket Mode")
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{SLACK_API_BASE}/apps.connections.open",
                headers={"Authorization": f"Bearer {app_token}"},
            )
            body = response.json()
        if response.status_code != 200 or not body.get("ok"):
            raise RuntimeError(f"apps.connections.open failed: {body.get('error', body)}")
        return body["url"]

    async def _connect_and_read(self) -> None:
        import websockets

        url = await self._open_connection_url()
        async with websockets.connect(url, ping_interval=30) as ws:
            self._ws = ws
            async for raw in ws:
                await self._handle_frame(raw)
            self._ws = None

    async def _handle_frame(self, raw) -> None:
        try:
            frame = json.loads(raw)
        except (ValueError, TypeError):
            return

        payload = frame.get("payload") or {}
        ack = {"type": "pong"} if frame.get("type") == "ping" else {"type": "ack"}
        if frame.get("id"):
            ack["id"] = frame["id"]
        try:
            await self._ws.send(json.dumps(ack))  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001 - an unacked frame is redelivered by Slack
            log.warning("Slack Socket Mode ack failed for envelope %s: %s", frame.get("id"), exc)

        if frame.get("type") != "events_api" or payload.get("type") != "event_callback":
            return

        event = parse_slack_event(payload.get("event") or {})
        if event is None:
            return
        # A message edited or re-announced (Slack bumps the envelope on replies
        # to a message) must not start a second run: only the original post has
        # event_ts == ts.
        if payload.get("event", {}).get("ts") != payload.get("event", {}).get("event_ts"):
            return
        await self._process(event)

    async def _process(self, event: SlackEvent) -> None:
        session_factory = self._services.session_factory
        async with session_factory() as session:
            response_text = await process_slack_message(self._services, session, event)
            await session.commit()

        # Commands produce an immediate text response.
        if response_text and event.channel_id:
            await deliver_to_slack(self._services, event.channel_id, response_text)


# ---------------------------------------------------------------------------
# Delivery listener (outgoing: bot -> Slack)
# ---------------------------------------------------------------------------


class SlackDeliveryListener:
    """Subscribes to the EventBus and delivers bot messages to Slack DMs.

    When a bot posts a message in a thread that has a ``slack:{channel_id}``
    external reference, this listener sends the message text to the Slack DM
    via chat.postMessage.
    """

    def __init__(self, services: Services) -> None:
        self._services = services
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="slack-delivery")
        log.info("Slack delivery listener started")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log.info("Slack delivery listener stopped")

    async def _loop(self) -> None:
        bus = self._services.bus
        # Subscribe to all threads (thread_id=None) so we can filter for Slack ones.
        async with bus.subscribe(thread_id=None) as queue:
            while self._running:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                except TimeoutError:
                    continue
                if event is None:
                    # Bus closed
                    break
                if event.get("event") != "message.created":
                    continue
                await self._handle_event(event)

    async def _handle_event(self, event: dict) -> None:
        thread_id = event.get("thread_id")
        data = event.get("data", {})
        if not thread_id or not data:
            return

        # Only deliver messages from bots (not from the Slack user or system)
        sender_kind = data.get("sender_kind")
        if sender_kind != "bot":
            return

        # Look up the thread to check for a Slack external_ref
        try:
            async with self._services.session_factory() as session:
                thread = await session.get(Thread, thread_id)
                if thread is None or not thread.external_ref:
                    return
                channel_id = _parse_channel_id_from_ref(thread.external_ref)
                if channel_id is None:
                    return

                content = data.get("content", "")
                if not content:
                    return

                await deliver_to_slack(self._services, channel_id, content)
        except Exception:
            log.exception("Failed to deliver bot message to Slack DM (thread=%s)", thread_id)

