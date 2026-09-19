"""Telegram channel adapter for OpenBot.

Provides a webhook endpoint that receives Telegram updates, maps each Telegram
user to a persistent thread, and delivers bot replies via the Telegram Bot API.

Usage:
    1. Create a Telegram bot via @BotFather and obtain the bot token.
    2. Set TELEGRAM_BOT_TOKEN in your .env file.
    3. Set TELEGRAM_WEBHOOK_SECRET for HMAC validation of incoming updates.
    4. Point Telegram's webhook to https://your-domain/api/v1/channels/telegram/webhook
    5. The adapter automatically maps Telegram users to threads and delivers replies.

Thread mapping:
    - Each Telegram user gets exactly one active thread (external_ref = "telegram:{chat_id}").
    - The thread persists until the user issues /new, which creates a fresh thread.
    - Thread history is never merged across different Telegram users.
"""
from __future__ import annotations

import hashlib
import hmac
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
TELEGRAM_USER_THREAD_KIND = "chat"  # Regular conversation threads
TELEGRAM_NEW_THREAD_PREFIX = "telegram:new:"


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


def validate_webhook_signature(secret: str, body: bytes, signature: str) -> bool:
    """Validate Telegram webhook HMAC signature."""
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


async def get_or_create_telegram_actor(session: AsyncSession, user_id: int, first_name: str,
                                       username: str | None) -> Actor:
    """Get or create a Telegram user actor."""
    handle = f"tg_{user_id}"
    actor = (await session.execute(select(Actor).where(Actor.handle == handle))).scalar_one_or_none()
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


async def get_or_create_thread(services: Services, session: AsyncSession, chat_id: int,
                               actor: Actor) -> Thread:
    """Get or create a thread for a Telegram chat."""
    external_ref = f"{TELEGRAM_PREFIX}{chat_id}"
    thread = (await session.execute(
        select(Thread).where(Thread.external_ref == external_ref)
    )).scalar_one_or_none()
    
    if thread is None:
        thread = await create_thread(
            services,
            session,
            title=f"Telegram {actor.name}",
            handles=[],
            created_by=actor,
            external_ref=external_ref,
            include_human=False,
            kind=TELEGRAM_USER_THREAD_KIND,
        )
    return thread


async def handle_telegram_command(services: Services, session: AsyncSession, update: TelegramUpdate,
                                  actor: Actor) -> bool:
    """Handle a /new command from Telegram. Returns True if handled."""
    if update.command != "new":
        return False
    
    # Create a new thread for this user
    external_ref = f"{TELEGRAM_PREFIX}{update.chat_id}"
    
    # Mark old thread as finished (keep history but remove external_ref so new messages go to new thread)
    old_thread = (await session.execute(
        select(Thread).where(Thread.external_ref == external_ref)
    )).scalar_one_or_none()
    
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
        kind=TELEGRAM_USER_THREAD_KIND,
    )
    
    return True


async def send_telegram_message(bot_token: str, chat_id: int, text: str) -> dict | None:
    """Send a message to a Telegram chat."""
    if not bot_token:
        log.warning("Telegram bot token not configured")
        return None
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json={
                "chat_id": chat_id,
                "text": text,
            })
            if response.status_code == 200:
                return response.json()
            else:
                log.error(f"Telegram API error: {response.status_code} - {response.text}")
                return None
    except Exception:
        log.exception("Failed to send Telegram message")
        return None


async def handle_telegram_message(services: Services, session: AsyncSession, update: TelegramUpdate) -> str:
    """Handle an incoming Telegram message. Returns the response text."""
    # Check if it's a command
    if update.is_command:
        if update.command == "new":
            await handle_telegram_command(services, session, update, await get_or_create_telegram_actor(
                session, update.user_id, update.user_first_name, update.user_username
            ))
            return "✨ New conversation started. I've forgotten our previous discussion."
        elif update.command == "start":
            return "👋 Welcome! I'm your AI assistant. Send me a message to get started."
        elif update.command == "help":
            return "💡 Commands:\n/new - Start a new conversation\n/start - Welcome message\n/help - Show this help"
        else:
            return f"❓ Unknown command: /{update.command}"
    
    # Get or create the user actor
    actor = await get_or_create_telegram_actor(session, update.user_id, update.user_first_name, update.user_username)
    
    # Get or create the thread for this user
    thread = await get_or_create_thread(services, session, update.chat_id, actor)
    
    # Post the message to the thread
    try:
        await post_message(
            services,
            session,
            thread_id=thread.id,
            sender=actor,
            content=update.text,
            to_handles=[],
        )
        return f"✅ Message received. Thread: {thread.id}"
    except Exception:
        log.exception("Failed to process Telegram message")
        return "❌ Error processing message"


async def deliver_to_telegram(services: Services, chat_id: int, text: str) -> bool:
    """Deliver a bot reply to Telegram."""
    bot_token = services.settings.telegram_bot_token
    if not bot_token:
        return False
    result = await send_telegram_message(bot_token, chat_id, text)
    return result is not None


async def get_thread_for_telegram_chat(session: AsyncSession, chat_id: int) -> Thread | None:
    """Get the active thread for a Telegram chat."""
    external_ref = f"{TELEGRAM_PREFIX}{chat_id}"
    return (await session.execute(
        select(Thread).where(Thread.external_ref == external_ref)
    )).scalar_one_or_none()