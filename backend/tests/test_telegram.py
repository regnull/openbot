"""Tests for Telegram channel adapter.

Covers:
1. Telegram update parsing
2. Thread mapping: user creates thread on first message, stays on same thread
3. /new command creates a fresh thread
4. Thread context isolation between different Telegram users
5. Webhook endpoint integration
6. Async delivery: bot messages in Telegram threads are delivered to Telegram
7. DeliveryListener start/stop lifecycle
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from openbot.channels.telegram import (
    TelegramDeliveryListener,
    TelegramUpdate,
    _parse_chat_id_from_ref,
    deliver_to_telegram,
    get_or_create_telegram_actor,
    get_or_create_thread,
    handle_telegram_command,
    parse_telegram_update,
    process_telegram_message,
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
        actor = await get_or_create_telegram_actor(session, update.user_id, update.user_first_name, update.user_username)
        response = await handle_telegram_command(services, session, update, actor)
        await session.commit()

    assert response is not None
    assert "New conversation" in response

    # Verify old thread no longer has external_ref, new thread does
    async with services.session_factory() as session:
        old_thread = await session.get(Thread, thread1.id)
        assert old_thread.external_ref is None  # Unlinked

        # A new thread with the same external_ref should exist
        new_thread = (
            await session.execute(
                select(Thread).where(Thread.external_ref == "telegram:5555")
            )
        ).scalar_one_or_none()
        assert new_thread is not None
        assert new_thread.id != thread1.id


@pytest.mark.asyncio
async def test_handle_help_command_returns_response(services):
    """All built-in commands return expected responses via handle_telegram_command."""
    commands = [
        ("/start", "Welcome"),
        ("/help", "Commands"),
        ("/unknown", "Unknown command"),
    ]

    for cmd_text, expected_fragment in commands:
        command_name = cmd_text.lstrip("/").split()[0]
        update = TelegramUpdate(
            update_id=700,
            message_id=80,
            chat_id=5001,
            user_id=6001,
            text=cmd_text,
            user_first_name="Frank",
            user_username="frank",
            is_command=True,
            command=command_name,
        )

        async with services.session_factory() as session:
            actor = await get_or_create_telegram_actor(
                session, update.user_id, update.user_first_name, update.user_username
            )
            response = await handle_telegram_command(services, session, update, actor)
            await session.commit()

        assert response is not None, f"Expected response for {cmd_text}"
        assert expected_fragment in response, f"Expected '{expected_fragment}' in response for {cmd_text}"


# ---------------------------------------------------------------------------
# process_telegram_message tests (command vs. message flow)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_command_returns_response(services):
    """Commands produce an immediate response text."""
    update = TelegramUpdate(
        update_id=200,
        message_id=20,
        chat_id=7000,
        user_id=7000,
        text="/start",
        user_first_name="Frank",
        user_username="frank",
        is_command=True,
        command="start",
    )

    async with services.session_factory() as session:
        response = await process_telegram_message(services, session, update)
        await session.commit()

    assert response is not None
    assert "Welcome" in response


@pytest.mark.asyncio
async def test_process_message_returns_none(services):
    """Regular messages return None (response is async)."""
    update = TelegramUpdate(
        update_id=201,
        message_id=21,
        chat_id=7001,
        user_id=7001,
        text="Hello bot",
        user_first_name="Grace",
        user_username="grace",
    )

    async with services.session_factory() as session:
        response = await process_telegram_message(services, session, update)
        await session.commit()

    assert response is None

    # Verify the message was posted to a thread
    async with services.session_factory() as session:
        thread = (
            await session.execute(
                select(Thread).where(Thread.external_ref == "telegram:7001")
            )
        ).scalar_one_or_none()
        assert thread is not None


@pytest.mark.asyncio
async def test_process_new_command_creates_thread(services):
    """The /new command via process_telegram_message creates a fresh thread."""
    # Create initial thread
    update1 = TelegramUpdate(
        update_id=300,
        message_id=30,
        chat_id=8000,
        user_id=8000,
        text="First message",
        user_first_name="Hank",
        user_username="hank",
    )
    async with services.session_factory() as session:
        await process_telegram_message(services, session, update1)
        await session.commit()

    # Verify initial thread exists
    async with services.session_factory() as session:
        t1 = (
            await session.execute(
                select(Thread).where(Thread.external_ref == "telegram:8000")
            )
        ).scalar_one_or_none()
        assert t1 is not None

    # Issue /new
    update_new = TelegramUpdate(
        update_id=301,
        message_id=31,
        chat_id=8000,
        user_id=8000,
        text="/new",
        user_first_name="Hank",
        user_username="hank",
        is_command=True,
        command="new",
    )
    async with services.session_factory() as session:
        response = await process_telegram_message(services, session, update_new)
        await session.commit()

    assert response is not None
    assert "New conversation" in response

    # Verify old thread is unlinked, new one exists
    async with services.session_factory() as session:
        old = await session.get(Thread, t1.id)
        assert old.external_ref is None

        t2 = (
            await session.execute(
                select(Thread).where(Thread.external_ref == "telegram:8000")
            )
        ).scalar_one_or_none()
        assert t2 is not None
        assert t2.id != t1.id


# ---------------------------------------------------------------------------
# End-to-end: initial user → stays on thread → /new → isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_user_stays_on_same_thread(services):
    """User sends multiple messages; all go to the same thread."""
    for i in range(3):
        update = TelegramUpdate(
            update_id=400 + i,
            message_id=40 + i,
            chat_id=9000,
            user_id=9000,
            text=f"Message {i}",
            user_first_name="Iris",
            user_username="iris",
        )
        async with services.session_factory() as session:
            await process_telegram_message(services, session, update)
            await session.commit()

    async with services.session_factory() as session:
        threads = (
            await session.execute(
                select(Thread).where(Thread.external_ref == "telegram:9000")
            )
        ).scalars().all()

    assert len(threads) == 1


@pytest.mark.asyncio
async def test_e2e_new_command_isolates_threads(services):
    """User sends messages, issues /new, sends more messages — two distinct threads."""
    # First conversation
    for i in range(2):
        update = TelegramUpdate(
            update_id=500 + i,
            message_id=50 + i,
            chat_id=9100,
            user_id=9100,
            text=f"First conv {i}",
            user_first_name="Jake",
            user_username="jake",
        )
        async with services.session_factory() as session:
            await process_telegram_message(services, session, update)
            await session.commit()

    # /new command
    update_new = TelegramUpdate(
        update_id=502,
        message_id=52,
        chat_id=9100,
        user_id=9100,
        text="/new",
        user_first_name="Jake",
        user_username="jake",
        is_command=True,
        command="new",
    )
    async with services.session_factory() as session:
        await process_telegram_message(services, session, update_new)
        await session.commit()

    # Second conversation
    for i in range(2):
        update = TelegramUpdate(
            update_id=510 + i,
            message_id=60 + i,
            chat_id=9100,
            user_id=9100,
            text=f"Second conv {i}",
            user_first_name="Jake",
            user_username="jake",
        )
        async with services.session_factory() as session:
            await process_telegram_message(services, session, update)
            await session.commit()

    async with services.session_factory() as session:
        # Old thread should have no external_ref
        all_threads = (
            await session.execute(select(Thread).where(Thread.title == "Telegram Jake"))
        ).scalars().all()
        archived = [t for t in all_threads if t.external_ref is None]
        active = [t for t in all_threads if t.external_ref == "telegram:9100"]

        assert len(archived) == 1
        assert len(active) == 1
        assert archived[0].id != active[0].id


@pytest.mark.asyncio
async def test_e2e_different_users_isolated(services):
    """Two different Telegram users never share thread context."""
    update_alice = TelegramUpdate(
        update_id=600,
        message_id=70,
        chat_id=9200,
        user_id=9200,
        text="Alice's message",
        user_first_name="Alice",
        user_username="alice",
    )
    update_bob = TelegramUpdate(
        update_id=601,
        message_id=71,
        chat_id=9300,
        user_id=9300,
        text="Bob's message",
        user_first_name="Bob",
        user_username="bob",
    )

    async with services.session_factory() as session:
        await process_telegram_message(services, session, update_alice)
        await session.commit()
    async with services.session_factory() as session:
        await process_telegram_message(services, session, update_bob)
        await session.commit()

    async with services.session_factory() as session:
        thread_a = (
            await session.execute(
                select(Thread).where(Thread.external_ref == "telegram:9200")
            )
        ).scalar_one_or_none()
        thread_b = (
            await session.execute(
                select(Thread).where(Thread.external_ref == "telegram:9300")
            )
        ).scalar_one_or_none()

    assert thread_a is not None
    assert thread_b is not None
    assert thread_a.id != thread_b.id


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
# _parse_chat_id_from_ref tests
# ---------------------------------------------------------------------------


def test_parse_chat_id_from_ref_valid():
    assert _parse_chat_id_from_ref("telegram:12345") == 12345
    assert _parse_chat_id_from_ref("telegram:-100123") == -100123


def test_parse_chat_id_from_ref_invalid():
    assert _parse_chat_id_from_ref("telegram:abc") is None
    assert _parse_chat_id_from_ref("not-telegram:123") is None
    assert _parse_chat_id_from_ref("") is None
    assert _parse_chat_id_from_ref(None) is None


# ---------------------------------------------------------------------------
# TelegramDeliveryListener tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delivery_listener_delivers_bot_message(services):
    """When a bot posts in a Telegram thread, the listener delivers to Telegram."""
    # Set up a Telegram thread
    async with services.session_factory() as session:
        actor = await get_or_create_telegram_actor(session, 3001, "TestUser", "testuser")
        thread = await get_or_create_thread(services, session, chat_id=3001, actor=actor)
        thread_id = thread.id
        await session.commit()

    # Track calls to deliver_to_telegram
    delivered: list[tuple[int, str]] = []

    async def mock_deliver(services, chat_id, text):
        delivered.append((chat_id, text))
        return True

    # Patch deliver_to_telegram
    import openbot.channels.telegram as tg_mod
    original = tg_mod.deliver_to_telegram
    tg_mod.deliver_to_telegram = mock_deliver
    try:
        # Start the listener first so its queue is subscribed before the event fires.
        listener = TelegramDeliveryListener(services)
        await listener.start()
        # Give the listener's queue a moment to connect to the bus.
        await asyncio.sleep(0.05)

        # Publish a bot message event
        await services.bus.publish(
            "message.created",
            thread_id,
            {
                "sender_kind": "bot",
                "sender_name": "Chief of Staff",
                "content": "Hello from the bot!",
            },
        )

        # Give the listener time to process
        await asyncio.sleep(0.3)
        await listener.stop()

        assert len(delivered) == 1
        assert delivered[0] == (3001, "Hello from the bot!")
    finally:
        tg_mod.deliver_to_telegram = original


@pytest.mark.asyncio
async def test_delivery_listener_ignores_human_messages(services):
    """Messages from humans/Telegram users should not be re-delivered to Telegram."""
    async with services.session_factory() as session:
        actor = await get_or_create_telegram_actor(session, 3002, "User2", "user2")
        thread = await get_or_create_thread(services, session, chat_id=3002, actor=actor)
        thread_id = thread.id
        await session.commit()

    delivered: list[tuple[int, str]] = []

    async def mock_deliver(services, chat_id, text):
        delivered.append((chat_id, text))
        return True

    import openbot.channels.telegram as tg_mod
    original = tg_mod.deliver_to_telegram
    tg_mod.deliver_to_telegram = mock_deliver
    try:
        # Publish a human message event
        # Start listener first
        listener = TelegramDeliveryListener(services)
        await listener.start()
        await asyncio.sleep(0.05)

        await services.bus.publish(
            "message.created",
            thread_id,
            {
                "sender_kind": "external",
                "sender_name": "User2",
                "content": "Hello from user",
            },
        )

        await asyncio.sleep(0.3)
        await listener.stop()

        assert len(delivered) == 0
    finally:
        tg_mod.deliver_to_telegram = original


@pytest.mark.asyncio
async def test_delivery_listener_ignores_non_telegram_threads(services):
    """Messages in non-Telegram threads should not trigger delivery."""
    from openbot.runtime.delivery import create_thread as _create_thread

    async with services.session_factory() as session:
        from openbot.seed import ensure_human_actor
        await ensure_human_actor(services)
        thread = await _create_thread(
            services,
            session,
            title="Regular thread",
            handles=[],
            created_by=None,
            external_ref=None,
            include_human=False,
        )
        thread_id = thread.id
        await session.commit()

    delivered: list[tuple[int, str]] = []

    async def mock_deliver(services, chat_id, text):
        delivered.append((chat_id, text))
        return True

    import openbot.channels.telegram as tg_mod
    original = tg_mod.deliver_to_telegram
    tg_mod.deliver_to_telegram = mock_deliver
    try:
        # Start listener first
        listener = TelegramDeliveryListener(services)
        await listener.start()
        await asyncio.sleep(0.05)

        await services.bus.publish(
            "message.created",
            thread_id,
            {
                "sender_kind": "bot",
                "sender_name": "Bot",
                "content": "Bot reply in non-Telegram thread",
            },
        )

        await asyncio.sleep(0.3)
        await listener.stop()

        assert len(delivered) == 0
    finally:
        tg_mod.deliver_to_telegram = original


@pytest.mark.asyncio
async def test_delivery_listener_start_stop_idempotent(services):
    """Starting/stopping multiple times is safe."""
    listener = TelegramDeliveryListener(services)
    await listener.start()
    await listener.start()  # second start is a no-op
    await listener.stop()
    await listener.stop()  # second stop is a no-op
    # No exception means success
