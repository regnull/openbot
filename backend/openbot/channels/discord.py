"""Discord channel adapter for OpenBot.

Receives Discord DMs, maps each Discord user to a persistent thread, and
delivers bot replies via the Discord REST API.

Transport:
    - ``gateway`` (default): A websocket connection to the Discord Gateway
      (identify + heartbeat + DISPATCH). No public URL needed.
    - ``webhook``: Interactions-only endpoint (slash commands) that Discord
      sends interactions to; message events still need the gateway, so webhook
      mode exists for health/status and command responses only.

Usage (gateway):
    1. Create a Discord application at https://discord.com/developers/applications
       and add a Bot to it. Enable the Message Content intent.
    2. Invite the bot with the ``bot`` scope; users message it directly.
    3. Set DISCORD_BOT_TOKEN in your .env file (or the settings page).
    4. The adapter connects to the gateway automatically on server startup.

Thread mapping:
    - Each Discord DM channel gets exactly one active thread
      (external_ref = "discord:{channel_id}").
    - The thread persists until the user issues /new, which creates a fresh thread.
    - Thread history is never merged across different Discord DM channels.

Delivery flow:
    - Gateway DISPATCH (or webhook interaction) -> posted to thread asynchronously.
    - The ActorSystem processes the message asynchronously (bot generates response).
    - A background DiscordDeliveryListener subscribes to the EventBus, detects bot
      messages in Discord threads, and delivers them via the Discord REST API.

Discord ids are snowflakes: numeric strings that exceed 32-bit range, so they
are kept as strings everywhere (unlike Telegram's integer chat ids).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openbot.db.models import Actor, ExternalProfile, Thread
from openbot.runtime.delivery import create_thread, post_message
from openbot.services import Services

log = logging.getLogger(__name__)

DISCORD_PREFIX = "discord:"
DISCORD_THREAD_KIND = "chat"

DISCORD_API_BASE = "https://discord.com/api/v10"
# Gateway v10; intents value 1 << 12 (Message Content), the only intent this
# adapter needs to read DM text.
DISCORD_GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"
DISCORD_MESSAGE_CONTENT_INTENT = 1 << 12

# Gateway opcodes (https://discord.com/developers/docs/topics/opcodes-and-status-codes#gateway)
OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11


@dataclass
class DiscordMessage:
    """Parsed Discord DM."""
    id: str | None
    channel_id: str
    author_id: str
    content: str
    author_username: str
    is_command: bool = False
    command: str | None = None


def parse_discord_message(data: dict) -> DiscordMessage | None:
    """Parse a raw Discord MESSAGE_CREATE gateway event into our internal representation.

    Only DMs (channels without a ``guild_id``) are accepted; guild messages are
    ignored so the bot never answers in shared servers.
    """
    channel = data.get("channel") or {}
    if data.get("guild_id") is not None or channel.get("type") != 1:
        return None

    author = data.get("author") or {}
    content = data.get("content", "")
    if not content or not isinstance(content, str):
        return None
    if author.get("bot"):
        # Never reply to ourselves or other bots: that is a reply loop.
        return None

    channel_id = data.get("channel_id") or channel.get("id")
    author_id = author.get("id")
    if not channel_id or not author_id:
        return None

    is_command = content.startswith("/")
    command = None
    if is_command:
        match = re.match(r"^/(\w+)(?:\s+.*)?$", content)
        if match:
            command = match.group(1).lower()

    return DiscordMessage(
        id=data.get("id"),
        channel_id=channel_id,
        author_id=author_id,
        content=content,
        author_username=author.get("username", ""),
        is_command=is_command,
        command=command,
    )


async def get_or_create_discord_actor(
    session: AsyncSession, user_id: str, username: str
) -> Actor:
    """Get or create a Discord user actor."""
    handle = f"dc_{user_id}"
    actor = (
        await session.execute(select(Actor).where(Actor.handle == handle))
    ).scalar_one_or_none()
    if actor is None:
        actor = Actor(
            kind="external",
            handle=handle,
            name=username or f"Discord {user_id}",
            description=f"Discord user {user_id}",
            external=ExternalProfile(webhook_url=None, webhook_secret=None),
        )
        session.add(actor)
        await session.flush()
    else:
        # Update name if changed
        if username and actor.name != username:
            actor.name = username
    return actor


async def get_or_create_thread(
    services: Services, session: AsyncSession, channel_id: str, actor: Actor
) -> Thread:
    """Get or create a thread for a Discord DM channel."""
    external_ref = f"{DISCORD_PREFIX}{channel_id}"
    thread = (
        await session.execute(
            select(Thread).where(Thread.external_ref == external_ref)
        )
    ).scalar_one_or_none()

    if thread is None:
        thread = await create_thread(
            services,
            session,
            title=f"Discord {actor.name}",
            handles=[],
            created_by=actor,
            external_ref=external_ref,
            include_human=False,
            kind=DISCORD_THREAD_KIND,
        )
    return thread


async def handle_discord_command(
    services: Services, session: AsyncSession, message: DiscordMessage, actor: Actor
) -> str | None:
    """Handle a Discord command. Returns response text, or None for non-commands."""
    if not message.is_command:
        return None

    if message.command == "new":
        external_ref = f"{DISCORD_PREFIX}{message.channel_id}"

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
            title=f"Discord {actor.name}",
            handles=[],
            created_by=actor,
            external_ref=external_ref,
            include_human=False,
            kind=DISCORD_THREAD_KIND,
        )

        return "\u2728 New conversation started. I've forgotten our previous discussion."

    if message.command == "start":
        return "\U0001f44b Welcome! I'm your AI assistant. Send me a message to get started."

    if message.command == "help":
        return (
            "\U0001f4a1 Commands:\n"
            "/new - Start a new conversation\n"
            "/start - Welcome message\n"
            "/help - Show this help"
        )

    return f"\u2753 Unknown command: /{message.command}"


async def send_discord_message(services: Services, channel_id: str, text: str) -> dict | None:
    """Send a message to a Discord DM channel."""
    bot_token = services.settings.discord_bot_token
    if not bot_token:
        log.warning("Discord bot token not configured")
        return None

    url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                json={"content": text[:2000]},  # Discord's hard limit per message
                headers={"Authorization": f"Bot {bot_token}"},
            )
            if response.status_code in (200, 201):
                return response.json()
            log.error("Discord API error: %s - %s", response.status_code, response.text)
            return None
    except Exception:
        log.exception("Failed to send Discord message")
        return None


async def process_discord_message(
    services: Services, session: AsyncSession, message: DiscordMessage
) -> str | None:
    """Process an incoming Discord DM.

    For commands, returns a response text to send immediately.
    For regular messages, posts to the thread (triggering async bot processing)
    and returns None -- the response will be delivered by DiscordDeliveryListener.
    """
    actor = await get_or_create_discord_actor(session, message.author_id, message.author_username)

    # Handle commands synchronously (they produce immediate responses)
    if message.is_command:
        return await handle_discord_command(services, session, message, actor)

    # Regular message: post to thread and let the bot process asynchronously
    thread = await get_or_create_thread(services, session, message.channel_id, actor)

    try:
        await post_message(
            services,
            session,
            thread_id=thread.id,
            sender=actor,
            content=message.content,
            to_handles=[],
        )
    except Exception:
        log.exception("Failed to post Discord message to thread %s", thread.id)
        return "\u274c Error processing message"

    # Return None -- the bot response will be delivered asynchronously
    return None


async def deliver_to_discord(services: Services, channel_id: str, text: str) -> bool:
    """Deliver a bot reply to Discord."""
    if not services.settings.discord_bot_token:
        return False
    result = await send_discord_message(services, channel_id, text)
    return result is not None


def _parse_channel_id_from_ref(external_ref: str | None) -> str | None:
    """Extract the DM channel id from a discord:* external_ref."""
    if external_ref and external_ref.startswith(DISCORD_PREFIX):
        channel_id = external_ref[len(DISCORD_PREFIX):]
        return channel_id or None
    return None


# ---------------------------------------------------------------------------
# Gateway transport (websocket)
# ---------------------------------------------------------------------------

# Base delay (seconds) for exponential back-off after a dropped connection.
_RECONNECT_BACKOFF_BASE: float = 2.0
_RECONNECT_BACKOFF_CAP: float = 60.0


class DiscordGatewayClient:
    """Keeps a websocket open to the Discord Gateway and feeds MESSAGE_CREATE
    events into the same processing pipeline used by the webhook transport.

    Lifecycle:
        - ``start()`` creates the background connection task.
        - ``stop()`` cancels it gracefully.

    The client identifies with the bot token, answers heartbeats on the
    interval the gateway asks for, and reconnects with exponential back-off on
    any drop. Requires the Message Content intent to be enabled on the bot.
    """

    def __init__(self, services: Services) -> None:
        self._services = services
        self._task: asyncio.Task | None = None
        self._running = False
        self._seq: int | None = None
        self._ws: object | None = None  # the active connection; set by _connect (tests patch it)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="discord-gateway")
        log.info("Discord gateway client started")

    async def stop(self) -> None:
        self._running = False
        if self._ws is not None:
            try:
                await self._ws.close()  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001 - a dead socket on shutdown changes nothing
                log.debug("Discord gateway close failed: %s", exc)
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log.info("Discord gateway client stopped")

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
                log.exception("Discord gateway error; reconnecting in %.1fs", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _RECONNECT_BACKOFF_CAP)

    async def _connect_and_read(self) -> None:
        import websockets

        bot_token = self._services.settings.discord_bot_token
        if not bot_token:
            log.warning("Discord bot token not configured; gateway paused")
            await asyncio.sleep(10)
            return

        async with websockets.connect(DISCORD_GATEWAY_URL, ping_interval=None) as ws:
            self._ws = ws
            hello = json.loads(await ws.recv())
            if hello.get("op") != OP_HELLO:
                raise RuntimeError(f"unexpected first gateway frame: {hello.get('op')}")
            interval_ms = hello["d"]["heartbeat_interval"]

            identify = {
                "op": OP_IDENTIFY,
                "d": {
                    "token": bot_token,
                    "intents": DISCORD_MESSAGE_CONTENT_INTENT,
                    "properties": {"os": "linux", "browser": "openbot", "device": "openbot"},
                },
            }
            await ws.send(json.dumps(identify))

            hb = asyncio.create_task(self._heartbeat(ws, interval_ms / 1000.0))
            try:
                async for raw in ws:
                    await self._handle_frame(raw)
            finally:
                hb.cancel()
                self._ws = None

    async def _heartbeat(self, ws, interval: float) -> None:
        try:
            while True:
                await asyncio.sleep(interval)
                await ws.send(json.dumps({"op": OP_HEARTBEAT, "d": self._seq}))
        except asyncio.CancelledError:
            return  # stop() ended the connection; nothing to report
        except Exception as exc:  # noqa: BLE001 - a failed heartbeat drops the socket; _loop reconnects
            log.debug("Discord heartbeat send failed; connection will be re-established: %s", exc)

    async def _handle_frame(self, raw) -> None:
        try:
            frame = json.loads(raw)
        except (ValueError, TypeError):
            return
        if frame.get("op") == OP_HEARTBEAT_ACK:
            return
        if frame.get("op") != OP_DISPATCH:
            return

        self._seq = frame.get("s", self._seq)
        if frame.get("t") != "MESSAGE_CREATE":
            return

        message = parse_discord_message(frame.get("d") or {})
        if message is None:
            return
        await self._process(message)

    async def _process(self, message: DiscordMessage) -> None:
        session_factory = self._services.session_factory
        async with session_factory() as session:
            response_text = await process_discord_message(self._services, session, message)
            await session.commit()

        # Commands produce an immediate text response.
        if response_text and message.channel_id:
            await deliver_to_discord(self._services, message.channel_id, response_text)


# ---------------------------------------------------------------------------
# Delivery listener (outgoing: bot -> Discord)
# ---------------------------------------------------------------------------


class DiscordDeliveryListener:
    """Subscribes to the EventBus and delivers bot messages to Discord DMs.

    When a bot posts a message in a thread that has a ``discord:{channel_id}``
    external reference, this listener sends the message text to the Discord DM
    via the REST API. Built on the Telegram listener: same event flow, only the
    prefix (string snowflake ids instead of integers) and the send call differ.
    """

    channel_prefix = DISCORD_PREFIX

    def __init__(self, services: Services) -> None:
        self._services = services
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="discord-delivery")
        log.info("Discord delivery listener started")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log.info("Discord delivery listener stopped")

    async def _loop(self) -> None:
        bus = self._services.bus
        # Subscribe to all threads (thread_id=None) so we can filter for Discord ones.
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

        # Only deliver messages from bots (not from the Discord user or system)
        sender_kind = data.get("sender_kind")
        if sender_kind != "bot":
            return

        # Look up the thread to check for a Discord external_ref
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

                await deliver_to_discord(self._services, channel_id, content)
        except Exception:
            log.exception("Failed to deliver bot message to Discord DM (thread=%s)", thread_id)
