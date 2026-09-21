"""Telegram channel adapter for OpenBot.

Receives Telegram updates, maps each Telegram user to a persistent thread, and
delivers bot replies via the Telegram Bot API.

Transport modes (TELEGRAM_TRANSPORT setting):
    - ``long_polling`` (default): Uses getUpdates with a long timeout. No public URL needed.
    - ``webhook``: Uses a webhook endpoint that Telegram sends updates to.

Usage (long-polling):
    1. Create a Telegram bot via @BotFather and obtain the bot token.
    2. Set TELEGRAM_BOT_TOKEN in your .env file.
    3. The adapter starts polling automatically on server startup.

Usage (webhook):
    1. Create a Telegram bot via @BotFather and obtain the bot token.
    2. Set TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET in your .env file.
    3. Set TELEGRAM_TRANSPORT=webhook.
    4. Point Telegram's webhook to https://your-domain/api/v1/channels/telegram/webhook

Thread mapping:
    - Each Telegram user gets exactly one active thread (external_ref = "telegram:{chat_id}").
    - The thread persists until the user issues /new, which creates a fresh thread.
    - Thread history is never merged across different Telegram users.

Delivery flow:
    - Update received (webhook or long-polling) -> posted to thread asynchronously.
    - The ActorSystem processes the message asynchronously (bot generates response).
    - A background TelegramDeliveryListener subscribes to the EventBus, detects bot
      messages in Telegram threads, and delivers them to Telegram via the Bot API.
"""
from __future__ import annotations

import asyncio
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

TELEGRAM_PREFIX = "telegram:"
TELEGRAM_THREAD_KIND = "chat"


@dataclass
class TelegramUpdate:
    """Parsed Telegram update."""
    update_id: int
    message_id: int | None
    chat_id: int
    user_id: int
    text: str
    user_first_name: str
    user_username: str | None
    is_command: bool = False
    command: str | None = None


def parse_telegram_update(data: dict) -> TelegramUpdate | None:
    """Parse a raw Telegram update into our internal representation."""
    update_id = data.get("update_id")
    message = data.get("message") or data.get("edited_message")
    if message is None or update_id is None:
        return None

    chat = message.get("chat", {})
    user = message.get("from", {})
    text = message.get("text", "")

    if not text or not isinstance(text, str):
        return None

    # Parse command if present
    is_command = text.startswith("/")
    command = None
    if is_command:
        match = re.match(r"^/(\w+)(?:\s+.*)?$", text)
        if match:
            command = match.group(1).lower()

    return TelegramUpdate(
        update_id=update_id,
        message_id=message.get("message_id"),
        chat_id=chat.get("id"),
        user_id=user.get("id"),
        text=text,
        user_first_name=user.get("first_name", ""),
        user_username=user.get("username"),
        is_command=is_command,
        command=command,
    )


def validate_webhook_token(secret: str, token: str) -> bool:
    """Validate Telegram webhook secret token.

    Telegram sends the raw secret token as-is in the
    ``X-Telegram-Bot-Api-Secret-Token`` header. We compare it against the
    configured secret using a constant-time comparison.
    """
    import hmac as _hmac

    return _hmac.compare_digest(secret, token)


async def get_or_create_telegram_actor(
    session: AsyncSession, user_id: int, first_name: str, username: str | None
) -> Actor:
    """Get or create a Telegram user actor."""
    handle = f"tg_{user_id}"
    actor = (
        await session.execute(select(Actor).where(Actor.handle == handle))
    ).scalar_one_or_none()
    if actor is None:
        actor = Actor(
            kind="external",
            handle=handle,
            name=first_name or f"Telegram {user_id}",
            description=f"Telegram user {user_id}",
            external=ExternalProfile(webhook_url=None, webhook_secret=None),
        )
        session.add(actor)
        await session.flush()
    else:
        # Update name if changed
        if first_name and actor.name != first_name:
            actor.name = first_name
    return actor


async def get_or_create_thread(
    services: Services, session: AsyncSession, chat_id: int, actor: Actor
) -> Thread:
    """Get or create a thread for a Telegram chat."""
    external_ref = f"{TELEGRAM_PREFIX}{chat_id}"
    thread = (
        await session.execute(
            select(Thread).where(Thread.external_ref == external_ref)
        )
    ).scalar_one_or_none()

    if thread is None:
        thread = await create_thread(
            services,
            session,
            title=f"Telegram {actor.name}",
            handles=[],
            created_by=actor,
            external_ref=external_ref,
            include_human=False,
            kind=TELEGRAM_THREAD_KIND,
        )
    return thread


async def handle_telegram_command(
    services: Services, session: AsyncSession, update: TelegramUpdate, actor: Actor
) -> str | None:
    """Handle a Telegram command. Returns response text, or None for non-commands."""
    if not update.is_command:
        return None

    if update.command == "new":
        external_ref = f"{TELEGRAM_PREFIX}{update.chat_id}"

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
            title=f"Telegram {actor.name}",
            handles=[],
            created_by=actor,
            external_ref=external_ref,
            include_human=False,
            kind=TELEGRAM_THREAD_KIND,
        )

        return "\u2728 New conversation started. I've forgotten our previous discussion."

    if update.command == "start":
        return "\U0001f44b Welcome! I'm your AI assistant. Send me a message to get started."

    if update.command == "help":
        return (
            "\U0001f4a1 Commands:\n"
            "/new - Start a new conversation\n"
            "/start - Welcome message\n"
            "/help - Show this help"
        )

    return f"\u2753 Unknown command: /{update.command}"


async def send_telegram_message(bot_token: str, chat_id: int, text: str) -> dict | None:
    """Send a message to a Telegram chat."""
    if not bot_token:
        log.warning("Telegram bot token not configured")
        return None

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json={"chat_id": chat_id, "text": text})
            if response.status_code == 200:
                return response.json()
            log.error("Telegram API error: %s - %s", response.status_code, response.text)
            return None
    except Exception:
        log.exception("Failed to send Telegram message")
        return None


async def process_telegram_message(
    services: Services, session: AsyncSession, update: TelegramUpdate
) -> str | None:
    """Process an incoming Telegram message.

    For commands, returns a response text to send immediately.
    For regular messages, posts to the thread (triggering async bot processing)
    and returns None -- the response will be delivered by TelegramDeliveryListener.
    """
    # Handle commands synchronously (they produce immediate responses)
    if update.is_command:
        actor = await get_or_create_telegram_actor(
            session, update.user_id, update.user_first_name, update.user_username
        )
        return await handle_telegram_command(services, session, update, actor)

    # Regular message: post to thread and let the bot process asynchronously
    actor = await get_or_create_telegram_actor(
        session, update.user_id, update.user_first_name, update.user_username
    )
    thread = await get_or_create_thread(services, session, update.chat_id, actor)

    try:
        await post_message(
            services,
            session,
            thread_id=thread.id,
            sender=actor,
            content=update.text,
            to_handles=[],
        )
    except Exception:
        log.exception("Failed to post Telegram message to thread %s", thread.id)
        return "\u274c Error processing message"

    # Return None -- the bot response will be delivered asynchronously
    return None


async def deliver_to_telegram(services: Services, chat_id: int, text: str) -> bool:
    """Deliver a bot reply to Telegram."""
    bot_token = services.settings.telegram_bot_token
    if not bot_token:
        return False
    result = await send_telegram_message(bot_token, chat_id, text)
    return result is not None


async def get_thread_for_telegram_chat(
    session: AsyncSession, chat_id: int
) -> Thread | None:
    """Get the active thread for a Telegram chat."""
    external_ref = f"{TELEGRAM_PREFIX}{chat_id}"
    return (
        await session.execute(
            select(Thread).where(Thread.external_ref == external_ref)
        )
    ).scalar_one_or_none()


def _parse_chat_id_from_ref(external_ref: str) -> int | None:
    """Extract the chat_id from a telegram:* external_ref."""
    if external_ref and external_ref.startswith(TELEGRAM_PREFIX):
        try:
            return int(external_ref[len(TELEGRAM_PREFIX) :])
        except (ValueError, TypeError):
            return None
    return None


# ---------------------------------------------------------------------------
# Long-polling transport
# ---------------------------------------------------------------------------

# Base delay (seconds) for exponential back-off after consecutive errors.
_POLL_BACKOFF_BASE: float = 2.0
_POLL_BACKOFF_CAP: float = 60.0
_POLL_TIMEOUT: int = 30  # Telegram long-poll timeout in seconds


class TelegramLongPoller:
    """Continuously polls Telegram's ``getUpdates`` endpoint and feeds updates
    into the same processing pipeline used by the webhook transport.

    Lifecycle:
        - ``start()`` creates the background polling task.
        - ``stop()`` cancels it gracefully.

    The poller tracks the last ``update_id`` it processed (the *offset*) so that
    already-handled updates are never re-delivered.  On network errors or
    unexpected API responses it backs off exponentially before retrying.
    """

    def __init__(self, services: Services) -> None:
        self._services = services
        self._task: asyncio.Task | None = None
        self._running = False
        self._offset: int = 0  # next update_id to fetch; 0 = newest only on first call

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="telegram-long-poller")
        log.info("Telegram long-poller started")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log.info("Telegram long-poller stopped")

    # -- internal -------------------------------------------------------------

    async def _loop(self) -> None:
        backoff = _POLL_BACKOFF_BASE
        while self._running:
            try:
                updates = await self._fetch_updates()
                # Successful fetch -- reset backoff.
                backoff = _POLL_BACKOFF_BASE
                for update_data in updates:
                    await self._handle_update(update_data)
            except asyncio.CancelledError:
                raise  # propagate so stop() sees clean cancellation
            except Exception:
                log.exception("Telegram long-poll error; retrying in %.1fs", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _POLL_BACKOFF_CAP)

    async def _fetch_updates(self) -> list[dict]:
        """Call ``getUpdates`` with a long timeout and return the update list."""
        bot_token = self._services.settings.telegram_bot_token
        if not bot_token:
            log.warning("Telegram bot token not configured; polling paused")
            await asyncio.sleep(10)
            return []

        url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
        params: dict = {"timeout": _POLL_TIMEOUT}
        if self._offset:
            params["offset"] = self._offset

        async with httpx.AsyncClient(timeout=_POLL_TIMEOUT + 10) as client:
            response = await client.get(url, params=params)

        if response.status_code != 200:
            log.error(
                "Telegram getUpdates error: %s - %s",
                response.status_code,
                response.text,
            )
            raise RuntimeError(f"getUpdates failed: {response.status_code}")

        body = response.json()
        if not body.get("ok"):
            log.error("Telegram getUpdates returned ok=false: %s", body)
            return []

        return body.get("result", [])

    async def _handle_update(self, update_data: dict) -> None:
        """Process a single raw Telegram update dict."""
        update = parse_telegram_update(update_data)
        if update is None:
            # Still advance offset so we don't re-fetch this update.
            self._offset = update_data["update_id"] + 1
            return

        session_factory = self._services.session_factory
        async with session_factory() as session:
            response_text = await process_telegram_message(
                self._services, session, update
            )

        # Commands produce an immediate text response.
        if response_text and update.chat_id:
            await deliver_to_telegram(self._services, update.chat_id, response_text)

        self._offset = update.update_id + 1


# ---------------------------------------------------------------------------
# Delivery listener (outgoing: bot -> Telegram)
# ---------------------------------------------------------------------------


class TelegramDeliveryListener:
    """Subscribes to the EventBus and delivers bot messages to Telegram chats.

    When a bot posts a message in a thread that has a ``telegram:{chat_id}``
    external reference, this listener sends the message text to the Telegram
    chat via the Bot API.

    Lifecycle:
        - ``start()`` creates the background task.
        - ``stop()`` cancels it gracefully.
    """

    def __init__(self, services: Services) -> None:
        self._services = services
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="telegram-delivery")
        log.info("Telegram delivery listener started")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log.info("Telegram delivery listener stopped")

    async def _loop(self) -> None:
        bus = self._services.bus
        # Subscribe to all threads (thread_id=None) so we can filter for Telegram ones.
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

        # Only deliver messages from bots (not from the Telegram user or system)
        sender_kind = data.get("sender_kind")
        if sender_kind != "bot":
            return

        # Look up the thread to check for a Telegram external_ref
        try:
            async with self._services.session_factory() as session:
                thread = await session.get(Thread, thread_id)
                if thread is None or not thread.external_ref:
                    return
                chat_id = _parse_chat_id_from_ref(thread.external_ref)
                if chat_id is None:
                    return

                # Deliver the bot's message to Telegram
                content = data.get("content", "")
                if not content:
                    return

                await deliver_to_telegram(self._services, chat_id, content)
        except Exception:
            log.exception("Failed to deliver bot message to Telegram chat (thread=%s)", thread_id)
