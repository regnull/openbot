"""Tests for Telegram channel adapter.

Covers:
1. Telegram update parsing
2. Thread mapping: user creates thread on first message, stays on same thread
3. /new command creates a fresh thread
4. Thread context isolation between different Telegram users
5. Webhook endpoint integration
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from openbot.channels.telegram import (
    TelegramUpdate,
    deliver_to_telegram,
    get_or_create_telegram_actor,
    get_or_create_thread,
    handle_telegram_command,
    handle_telegram_message,
    parse_telegram_update,
    validate_webhook_secret,
)
from openbot.db.models import Actor, Thread

# ---------------------------------------------------------------------------
# TelegramUpdate parsing tests
# ---------------------------------------------------------------------------

class TestParseTelegramUpdate:
    def test_parse_basic_message(self):
        data = {
            "update_id": 123,
            "message": {
                "message_id": 1,
                "chat": {"id": 42},
                "from": {"id": 100, "first_name": "Alice", "username": "alice"},
                "text": "Hello bot",
            },
        }
        update = parse_telegram_update(data)
        assert update is not None
        assert update.update_id == 123
        assert update.chat_id == 42
        assert update.user_id == 100
        assert update.text == "Hello bot"
        assert update.user_first_name == "Alice"
        assert update.user_username == "alice"
        assert update.is_command is False
        assert update.command is None

    def test_parse_command(self):
        data = {
            "update_id": 200,
            "message": {
                "message_id": 5,
                "chat": {"id": 99},
                "from": {"id": 200, "first_name": "Bob"},
                "text": "/new",
            },
        }
        update = parse_telegram_update(data)
        assert update is not None
        assert update.is_command is True
        assert update.command == "new"

    def test_parse_command_with_args(self):
        data = {
            "update_id": 201,
            "message": {
                "message_id": 6,
                "chat": {"id": 99},
                "from": {"id": 200, "first_name": "Bob"},
                "text": "/start something",
            },
        }
        update = parse_telegram_update(data)
        assert update is not None
        assert update.command == "start"

    def test_parse_no_message_returns_none(self):
        data = {"update_id": 1}  # No message field
        assert parse_telegram_update(data) is None

    def test_parse_no_text_returns_none(self):
        data = {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "chat": {"id": 42},
                "from": {"id": 100, "first_name": "Alice"},
                # No text field
            },
        }
        assert parse_telegram_update(data) is None

    def test_parse_empty_text_returns_none(self):
        data = {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "chat": {"id": 42},
                "from": {"id": 100, "first_name": "Alice"},
                "text": "",
            },
        }
        assert parse_telegram_update(data) is None

    def test_parse_callback_query(self):
        # Callback queries don't have a "message" with text; should be ignored
        data = {"update_id": 300, "callback_query": {"data": "btn1"}}
        assert parse_telegram_update(data) is None


# ---------------------------------------------------------------------------
# Actor creation tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_or_create_telegram_actor_creates_new(services):
    async with services.session_factory() as session:
        actor = await get_or_create_telegram_actor(session, 5555, "Alice", "alice")
        await session.commit()
        
        assert actor.handle == "tg_5555"
        assert actor.kind == "external"
        assert actor.name == "Alice"
        
        # Verify it's persisted
        found = await session.get(Actor, actor.id)
        assert found is not None
        assert found.handle == "tg_5555"


@pytest.mark.asyncio
async def test_get_or_create_telegram_actor_returns_existing(services):
    async with services.session_factory() as session:
        actor1 = await get_or_create_telegram_actor(session, 5555, "Alice", "alice")
        await session.commit()
    
    async with services.session_factory() as session:
        actor2 = await get_or_create_telegram_actor(session, 5555, "Alice Updated", "alice_v2")
        await session.commit()
        
        assert actor1.id == actor2.id
        assert actor2.name == "Alice Updated"


@pytest.mark.asyncio
async def test_get_or_create_telegram_actor_different_users(services):
    async with services.session_factory() as session:
        alice = await get_or_create_telegram_actor(session, 1000, "Alice", "alice")
        bob = await get_or_create_telegram_actor(session, 2000, "Bob", "bob")
        await session.commit()
        
        assert alice.id != bob.id
        assert alice.handle != bob.handle


# ---------------------------------------------------------------------------
# Thread mapping tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_or_create_thread_creates_new(services):
    async with services.session_factory() as session:
        actor = await get_or_create_telegram_actor(session, 5555, "Alice", "alice")
        thread = await get_or_create_thread(services, session, chat_id=5555, actor=actor)
        await session.commit()
        
        assert thread is not None
        assert thread.external_ref == "telegram:5555"
        
        # Verify it's persisted
        found = await session.get(Thread, thread.id)
        assert found is not None
        assert found.external_ref == "telegram:5555"


@pytest.mark.asyncio
async def test_get_or_create_thread_returns_existing(services):
    async with services.session_factory() as session:
        actor = await get_or_create_telegram_actor(session, 5555, "Alice", "alice")
        thread1 = await get_or_create_thread(services, session, chat_id=5555, actor=actor)
        await session.commit()
    
    async with services.session_factory() as session:
        actor = await get_or_create_telegram_actor(session, 5555, "Alice", "alice")
        thread2 = await get_or_create_thread(services, session, chat_id=5555, actor=actor)
        await session.commit()
        
        assert thread1.id == thread2.id


@pytest.mark.asyncio
async def test_different_users_get_different_threads(services):
    async with services.session_factory() as session:
        alice = await get_or_create_telegram_actor(session, 1000, "Alice", "alice")
        thread_a = await get_or_create_thread(services, session, chat_id=1000, actor=alice)
        
        bob = await get_or_create_telegram_actor(session, 2000, "Bob", "bob")
        thread_b = await get_or_create_thread(services, session, chat_id=2000, actor=bob)
        await session.commit()
        
        assert thread_a.id != thread_b.id
        assert thread_a.external_ref == "telegram:1000"
        assert thread_b.external_ref == "telegram:2000"


# ---------------------------------------------------------------------------
# /new command tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_new_command_creates_fresh_thread(services):
    # First message creates initial thread
    async with services.session_factory() as session:
        actor = await get_or_create_telegram_actor(session, 5555, "Alice", "alice")
        thread1 = await get_or_create_thread(services, session, chat_id=5555, actor=actor)
        await session.commit()
    
    # Issue /new command
    update = TelegramUpdate(
        update_id=100,
        message_id=10,
        chat_id=5555,
        user_id=5555,
        text="/new",
        user_first_name="Alice",
        user_username="alice",
        is_command=True,
        command="new",
    )
    
    async with services.session_factory() as session:
        actor = await get_or_create_telegram_actor(session, 5555, "Alice", "alice")
        handled = await handle_telegram_command(services, session, update, actor)
        await session.commit()
        
        assert handled is True
        
        # Old thread should have external_ref cleared
        old_thread = await session.get(Thread, thread1.id)
        assert old_thread.external_ref is None
        
        # New thread should exist with the same external_ref
        new_thread = (await session.execute(
            select(Thread).where(Thread.external_ref == "telegram:5555")
        )).scalar_one_or_none()
        
        assert new_thread is not None
        assert new_thread.id != thread1.id


@pytest.mark.asyncio
async def test_non_new_command_not_handled(services):
    update = TelegramUpdate(
        update_id=101,
        message_id=11,
        chat_id=5555,
        user_id=5555,
        text="/help",
        user_first_name="Alice",
        user_username="alice",
        is_command=True,
        command="help",
    )
    
    async with services.session_factory() as session:
        actor = await get_or_create_telegram_actor(session, 5555, "Alice", "alice")
        handled = await handle_telegram_command(services, session, update, actor)
        await session.commit()
        
        assert handled is False


# ---------------------------------------------------------------------------
# Message handling integration tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_first_message_creates_thread_and_actor(services):
    update = TelegramUpdate(
        update_id=1,
        message_id=1,
        chat_id=1001,
        user_id=2001,
        text="Hello bot!",
        user_first_name="Charlie",
        user_username="charlie",
    )
    
    async with services.session_factory() as session:
        response = await handle_telegram_message(services, session, update)
        await session.commit()
        
        assert "Message received" in response
    
    # Verify actor and thread were created
    async with services.session_factory() as session:
        actor = (await session.execute(
            select(Actor).where(Actor.handle == "tg_2001")
        )).scalar_one_or_none()
        assert actor is not None
        assert actor.name == "Charlie"
        
        thread = (await session.execute(
            select(Thread).where(Thread.external_ref == "telegram:1001")
        )).scalar_one_or_none()
        assert thread is not None


@pytest.mark.asyncio
async def test_handle_second_message_same_thread(services):
    update1 = TelegramUpdate(
        update_id=1,
        message_id=1,
        chat_id=1002,
        user_id=2002,
        text="First message",
        user_first_name="Dave",
        user_username="dave",
    )
    
    async with services.session_factory() as session:
        await handle_telegram_message(services, session, update1)
        await session.commit()
    
    update2 = TelegramUpdate(
        update_id=2,
        message_id=2,
        chat_id=1002,
        user_id=2002,
        text="Second message",
        user_first_name="Dave",
        user_username="dave",
    )
    
    async with services.session_factory() as session:
        await handle_telegram_message(services, session, update2)
        await session.commit()
    
    # Only one thread should exist for this chat
    async with services.session_factory() as session:
        threads = (await session.execute(
            select(Thread).where(Thread.external_ref == "telegram:1002")
        )).scalars().all()
        assert len(threads) == 1


@pytest.mark.asyncio
async def test_handle_new_command_fresh_thread_isolation(services):
    # First message
    update1 = TelegramUpdate(
        update_id=1,
        message_id=1,
        chat_id=1003,
        user_id=2003,
        text="First thread",
        user_first_name="Eve",
        user_username="eve",
    )
    
    async with services.session_factory() as session:
        await handle_telegram_message(services, session, update1)
        await session.commit()
    
    # /new command
    update_new = TelegramUpdate(
        update_id=2,
        message_id=2,
        chat_id=1003,
        user_id=2003,
        text="/new",
        user_first_name="Eve",
        user_username="eve",
        is_command=True,
        command="new",
    )
    
    async with services.session_factory() as session:
        await handle_telegram_message(services, session, update_new)
        await session.commit()
    
    # Message in new thread
    update3 = TelegramUpdate(
        update_id=3,
        message_id=3,
        chat_id=1003,
        user_id=2003,
        text="Second thread",
        user_first_name="Eve",
        user_username="eve",
    )
    
    async with services.session_factory() as session:
        await handle_telegram_message(services, session, update3)
        await session.commit()
    
    # Check threads: old should have no external_ref, new should have the ref
    async with services.session_factory() as session:
        # The old thread still exists but has no external_ref
        threads = (await session.execute(select(Thread))).scalars().all()
        active_threads = [t for t in threads if t.external_ref == "telegram:1003"]
        assert len(active_threads) == 1
        
        # The old thread is archived
        archived = [t for t in threads if t.external_ref is None and t.title == "Telegram Eve"]
        assert len(archived) >= 1


@pytest.mark.asyncio
async def test_different_users_different_thread_context(services):
    # Alice sends a message
    update_alice = TelegramUpdate(
        update_id=1,
        message_id=1,
        chat_id=3001,
        user_id=4001,
        text="Hi from Alice",
        user_first_name="Alice",
        user_username="alice",
    )
    
    async with services.session_factory() as session:
        await handle_telegram_message(services, session, update_alice)
        await session.commit()
    
    # Bob sends a message
    update_bob = TelegramUpdate(
        update_id=2,
        message_id=2,
        chat_id=3002,
        user_id=4002,
        text="Hi from Bob",
        user_first_name="Bob",
        user_username="bob",
    )
    
    async with services.session_factory() as session:
        await handle_telegram_message(services, session, update_bob)
        await session.commit()
    
    # Verify completely separate threads
    async with services.session_factory() as session:
        alice_thread = (await session.execute(
            select(Thread).where(Thread.external_ref == "telegram:3001")
        )).scalar_one_or_none()
        
        bob_thread = (await session.execute(
            select(Thread).where(Thread.external_ref == "telegram:3002")
        )).scalar_one_or_none()
        
        assert alice_thread is not None
        assert bob_thread is not None
        assert alice_thread.id != bob_thread.id


@pytest.mark.asyncio
async def test_command_handlers(services):
    # /start command
    update_start = TelegramUpdate(
        update_id=1,
        message_id=1,
        chat_id=5001,
        user_id=6001,
        text="/start",
        user_first_name="Frank",
        user_username="frank",
        is_command=True,
        command="start",
    )
    
    async with services.session_factory() as session:
        response = await handle_telegram_message(services, session, update_start)
        await session.commit()
    
    assert "Welcome" in response
    
    # /help command
    update_help = TelegramUpdate(
        update_id=2,
        message_id=2,
        chat_id=5001,
        user_id=6001,
        text="/help",
        user_first_name="Frank",
        user_username="frank",
        is_command=True,
        command="help",
    )
    
    async with services.session_factory() as session:
        response = await handle_telegram_message(services, session, update_help)
        await session.commit()
    
    assert "Commands" in response
    
    # Unknown command
    update_unknown = TelegramUpdate(
        update_id=3,
        message_id=3,
        chat_id=5001,
        user_id=6001,
        text="/unknown",
        user_first_name="Frank",
        user_username="frank",
        is_command=True,
        command="unknown",
    )
    
    async with services.session_factory() as session:
        response = await handle_telegram_message(services, session, update_unknown)
        await session.commit()
    
    assert "Unknown command" in response


# ---------------------------------------------------------------------------
# Deliver to Telegram tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deliver_to_telegram_no_token(services):
    # Without a token, delivery should return False
    result = await deliver_to_telegram(services, 12345, "test")
    assert result is False


# ---------------------------------------------------------------------------
# Thread kind tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_telegram_thread_kind_is_chat(services):
    async with services.session_factory() as session:
        actor = await get_or_create_telegram_actor(session, 5555, "Alice", "alice")
        thread = await get_or_create_thread(services, session, chat_id=5555, actor=actor)
        await session.commit()
        
        assert thread.kind == "chat"


# ---------------------------------------------------------------------------
# Webhook secret validation tests
# ---------------------------------------------------------------------------


class TestValidateWebhookSecret:
    """Tests for the validate_webhook_secret function.

    Telegram Bot API sends the raw secret token as-is in the
    ``X-Telegram-Bot-Api-Secret-Token`` header.  Validation must use
    constant-time comparison and skip when no secret is configured.
    """

    def test_matching_secret(self):
        assert validate_webhook_secret("my-secret", "my-secret") is True

    def test_mismatching_secret(self):
        assert validate_webhook_secret("my-secret", "wrong-token") is False

    def test_empty_secret_skips_validation(self):
        """When no secret is configured the endpoint must accept all requests."""
        assert validate_webhook_secret("", "anything") is True

    def test_none_secret_skips_validation(self):
        """None secret (config unset) must also skip validation."""
        assert validate_webhook_secret(None, "anything") is True  # type: ignore[arg-type]

    def test_empty_token_rejected(self):
        assert validate_webhook_secret("my-secret", "") is False

    def test_partial_match_rejected(self):
        assert validate_webhook_secret("my-secret", "my-") is False

    def test_case_sensitive(self):
        assert validate_webhook_secret("MySecret", "mysecret") is False