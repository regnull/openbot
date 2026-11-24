"""Tests for Discord channel adapter.

Covers:
1. Discord MESSAGE_CREATE parsing (DM-only, bot echoes dropped)
2. Thread mapping: user creates thread on first message, stays on same thread
3. /new command creates a fresh thread
4. Gateway client feeds events into the same processing pipeline
5. Async delivery: bot messages in Discord threads are delivered to Discord
6. DeliveryListener start/stop lifecycle
7. Status endpoint
8. Config validation
"""
from __future__ import annotations

import asyncio
import json

import pytest

from openbot.channels.discord import (
    DiscordDeliveryListener,
    DiscordGatewayClient,
    DiscordMessage,
    _parse_channel_id_from_ref,
    deliver_to_discord,
    get_or_create_discord_actor,
    get_or_create_thread,
    handle_discord_command,
    parse_discord_message,
    process_discord_message,
)
from openbot.db.models import Thread

# ---------------------------------------------------------------------------
# DiscordMessage parsing tests
# ---------------------------------------------------------------------------


def _dm_event_payload(content: str = "Hello bot", channel_id: str = "900000000000000001",
                      author_id: str = "111111111111111111", username: str = "alice",
                      bot: bool = False, guild: bool = False) -> dict:
    """A raw Discord MESSAGE_CREATE `d` payload shaped like the gateway sends it."""
    data = {
        "id": "500000000000000001",
        "channel_id": channel_id,
        "author": {"id": author_id, "username": username, "bot": bot},
        "content": content,
        "channel": {"id": channel_id, "type": 1 if not guild else 0},
    }
    if guild:
        data["guild_id"] = "700000000000000001"
    return data


class TestParseDiscordMessage:
    def test_parse_basic_dm(self):
        message = parse_discord_message(_dm_event_payload())
        assert message is not None
        assert message.channel_id == "900000000000000001"
        assert message.author_id == "111111111111111111"
        assert message.content == "Hello bot"
        assert message.author_username == "alice"
        assert message.is_command is False
        assert message.command is None

    def test_parse_command(self):
        message = parse_discord_message(_dm_event_payload("/new"))
        assert message is not None
        assert message.is_command is True
        assert message.command == "new"

    def test_parse_command_with_args(self):
        message = parse_discord_message(_dm_event_payload("/start something"))
        assert message is not None
        assert message.command == "start"

    def test_guild_message_returns_none(self):
        """The bot must never answer in shared servers, only DMs."""
        assert parse_discord_message(_dm_event_payload(guild=True)) is None

    def test_bot_author_returns_none(self):
        """Our own posts (and other bots) must not loop back in."""
        assert parse_discord_message(_dm_event_payload(bot=True)) is None

    def test_empty_content_returns_none(self):
        assert parse_discord_message(_dm_event_payload("")) is None

    def test_missing_author_returns_none(self):
        data = _dm_event_payload()
        del data["author"]
        assert parse_discord_message(data) is None


# ---------------------------------------------------------------------------
# Actor and thread mapping tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_create_discord_actor_creates_new(services):
    async with services.session_factory() as session:
        actor = await get_or_create_discord_actor(session, "111000111000111000", "alice")
        assert actor.handle == "dc_111000111000111000"
        assert actor.kind == "external"
        assert actor.name == "alice"


@pytest.mark.asyncio
async def test_get_or_create_discord_actor_returns_existing(services):
    async with services.session_factory() as session:
        a1 = await get_or_create_discord_actor(session, "222000222000222000", "bob")
        a2 = await get_or_create_discord_actor(session, "222000222000222000", "Bob Renamed")
        assert a1.id == a2.id
        assert a2.name == "Bob Renamed"


@pytest.mark.asyncio
async def test_get_or_create_thread_creates_new(services):
    async with services.session_factory() as session:
        actor = await get_or_create_discord_actor(session, "333000333000333000", "carol")
        thread = await get_or_create_thread(services, session, "900000000000000002", actor)
        assert thread.external_ref == "discord:900000000000000002"
        assert thread.kind == "chat"


@pytest.mark.asyncio
async def test_get_or_create_thread_returns_existing(services):
    async with services.session_factory() as session:
        actor = await get_or_create_discord_actor(session, "444000444000444000", "dan")
        t1 = await get_or_create_thread(services, session, "900000000000000003", actor)
        t2 = await get_or_create_thread(services, session, "900000000000000003", actor)
        assert t1.id == t2.id


@pytest.mark.asyncio
async def test_different_users_get_different_threads(services):
    async with services.session_factory() as session:
        a1 = await get_or_create_discord_actor(session, "555000555000555000", "u1")
        a2 = await get_or_create_discord_actor(session, "666000666000666000", "u2")
        t1 = await get_or_create_thread(services, session, "900000000000000010", a1)
        t2 = await get_or_create_thread(services, session, "900000000000000011", a2)
        assert t1.id != t2.id


# ---------------------------------------------------------------------------
# Command tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_new_command_creates_fresh_thread(services):
    async with services.session_factory() as session:
        actor = await get_or_create_discord_actor(session, "777000777000777000", "erin")
        old = await get_or_create_thread(services, session, "900000000000000020", actor)
        old_id = old.id

        msg = DiscordMessage(
            id="1", channel_id="900000000000000020", author_id="777000777000777000",
            content="/new", author_username="erin", is_command=True, command="new",
        )
        response = await handle_discord_command(services, session, msg, actor)
        assert "New conversation" in response

        # Old thread lost its external_ref; a new one owns it now.
        from sqlalchemy import select
        fresh = (
            await session.execute(
                select(Thread).where(Thread.external_ref == "discord:900000000000000020")
            )
        ).scalar_one()
        assert fresh.id != old_id


@pytest.mark.asyncio
async def test_handle_help_command_returns_response(services):
    async with services.session_factory() as session:
        actor = await get_or_create_discord_actor(session, "888000888000888000", "frank")
        msg = DiscordMessage(
            id="1", channel_id="900000000000000021", author_id="888000888000888000",
            content="/help", author_username="frank", is_command=True, command="help",
        )
        response = await handle_discord_command(services, session, msg, actor)
        assert "/new" in response


# ---------------------------------------------------------------------------
# process_discord_message tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_command_returns_response(services):
    async with services.session_factory() as session:
        msg = DiscordMessage(
            id="1", channel_id="900000000000000030", author_id="100000000000000001",
            content="/start", author_username="gina", is_command=True, command="start",
        )
        response = await process_discord_message(services, session, msg)
        assert "Welcome" in response


@pytest.mark.asyncio
async def test_process_message_posts_to_thread(services):
    """A fake inbound DM reaches the agent pipeline: actor + thread message created."""
    async with services.session_factory() as session:
        msg = DiscordMessage(
            id="1", channel_id="900000000000000031", author_id="100000000000000002",
            content="Hello there", author_username="hank", is_command=False, command=None,
        )
        result = await process_discord_message(services, session, msg)
        assert result is None  # bot reply arrives asynchronously via the listener
        await session.commit()

    async with services.session_factory() as session:
        from sqlalchemy import select
        thread = (
            await session.execute(
                select(Thread).where(Thread.external_ref == "discord:900000000000000031")
            )
        ).scalar_one()
        from openbot.db.models import Message
        messages = (
            await session.execute(select(Message).where(Message.thread_id == thread.id))
        ).scalars().all()
        assert len(messages) == 1
        assert messages[0].content == "Hello there"
        assert messages[0].sender_kind == "external"


# ---------------------------------------------------------------------------
# Delivery tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deliver_to_discord_no_token(services):
    result = await deliver_to_discord(services, "900000000000000040", "test")
    assert result is False


def test_parse_channel_id_from_ref_valid():
    assert _parse_channel_id_from_ref("discord:900000000000000001") == "900000000000000001"


def test_parse_channel_id_from_ref_invalid():
    assert _parse_channel_id_from_ref("discord:") is None
    assert _parse_channel_id_from_ref("not-discord:123") is None
    assert _parse_channel_id_from_ref("") is None
    assert _parse_channel_id_from_ref(None) is None


# ---------------------------------------------------------------------------
# DiscordDeliveryListener tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delivery_listener_delivers_bot_message(services):
    """When a bot posts in a Discord thread, the listener delivers to Discord."""
    async with services.session_factory() as session:
        actor = await get_or_create_discord_actor(session, "120000000000000001", "ivy")
        thread = await get_or_create_thread(services, session, "900000000000000050", actor)
        thread_id = thread.id
        await session.commit()

    delivered: list[tuple[str, str]] = []

    async def mock_deliver(services, channel_id, text):
        delivered.append((channel_id, text))
        return True

    import openbot.channels.discord as dc_mod
    original = dc_mod.deliver_to_discord
    dc_mod.deliver_to_discord = mock_deliver
    try:
        listener = DiscordDeliveryListener(services)
        await listener.start()
        await asyncio.sleep(0.05)

        await services.bus.publish(
            "message.created",
            thread_id,
            {
                "sender_kind": "bot",
                "sender_name": "Chief of Staff",
                "content": "Hello from the bot!",
            },
        )

        await asyncio.sleep(0.3)
        await listener.stop()

        assert len(delivered) == 1
        assert delivered[0] == ("900000000000000050", "Hello from the bot!")
    finally:
        dc_mod.deliver_to_discord = original


@pytest.mark.asyncio
async def test_delivery_listener_ignores_non_discord_threads(services):
    """Messages in non-Discord threads should not trigger delivery."""
    from openbot.runtime.delivery import create_thread as _create_thread
    from openbot.seed import ensure_human_actor

    async with services.session_factory() as session:
        await ensure_human_actor(services)
        thread = await _create_thread(
            services, session, title="Regular thread", handles=[], created_by=None,
            external_ref="telegram:12345", include_human=False,
        )
        thread_id = thread.id
        await session.commit()

    delivered: list[tuple[str, str]] = []

    async def mock_deliver(services, channel_id, text):
        delivered.append((channel_id, text))
        return True

    import openbot.channels.discord as dc_mod
    original = dc_mod.deliver_to_discord
    dc_mod.deliver_to_discord = mock_deliver
    try:
        listener = DiscordDeliveryListener(services)
        await listener.start()
        await asyncio.sleep(0.05)

        await services.bus.publish(
            "message.created",
            thread_id,
            {"sender_kind": "bot", "sender_name": "Bot", "content": "Not for Discord"},
        )

        await asyncio.sleep(0.3)
        await listener.stop()
        assert len(delivered) == 0
    finally:
        dc_mod.deliver_to_discord = original


@pytest.mark.asyncio
async def test_delivery_listener_start_stop_idempotent(services):
    listener = DiscordDeliveryListener(services)
    await listener.start()
    await listener.start()
    await listener.stop()
    await listener.stop()




# ---------------------------------------------------------------------------
# Gateway client tests (inbound path, no real network)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gateway_client_start_stop(services):
    client = DiscordGatewayClient(services)
    await client.start()
    assert client._running is True
    await client.stop()
    assert client._running is False
    await client.stop()  # second stop is a no-op


@pytest.mark.asyncio
async def test_gateway_frame_processes_dm_and_command(services):
    """A fake gateway MESSAGE_CREATE frame reaches the handler; /start gets an immediate reply."""
    client = DiscordGatewayClient(services)

    delivered: list[tuple[str, str]] = []

    async def mock_deliver(services, channel_id, text):
        delivered.append((channel_id, text))
        return True

    import openbot.channels.discord as dc_mod
    original = dc_mod.deliver_to_discord
    dc_mod.deliver_to_discord = mock_deliver
    try:
        frame = json.dumps({
            "op": 0, "s": 7, "t": "MESSAGE_CREATE",
            "d": _dm_event_payload("/start", channel_id="900000000000000060"),
        })
        await client._handle_frame(frame)
        assert client._seq == 7
        assert len(delivered) == 1
        assert delivered[0][0] == "900000000000000060"
        assert "Welcome" in delivered[0][1]

        # A regular DM frame posts to a thread and returns without direct delivery.
        frame2 = json.dumps({
            "op": 0, "s": 8, "t": "MESSAGE_CREATE",
            "d": _dm_event_payload("hi", channel_id="900000000000000061"),
        })
        await client._handle_frame(frame2)
        assert len(delivered) == 1

        async with services.session_factory() as session:
            from sqlalchemy import select
            thread = (
                await session.execute(
                    select(Thread).where(Thread.external_ref == "discord:900000000000000061")
                )
            ).scalar_one_or_none()
            assert thread is not None
    finally:
        dc_mod.deliver_to_discord = original


@pytest.mark.asyncio
async def test_gateway_ignores_non_message_frames(services):
    client = DiscordGatewayClient(services)
    await client._handle_frame(json.dumps({"op": 11}))          # heartbeat ack
    await client._handle_frame(json.dumps({"op": 0, "s": 9, "t": "READY", "d": {}}))
    await client._handle_frame("not json")
    assert client._seq == 9


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discord_status_endpoint(client, services):
    resp = await client.get("/api/v1/channels/discord/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is False  # no token in test
    assert body["transport"] == "gateway"


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


def test_discord_config_empty_token_means_unset():
    from openbot.config import Settings
    s = Settings(discord_bot_token="", _env_file=None)
    assert s.discord_bot_token is None


@pytest.mark.asyncio
async def test_settings_api_discord_token_roundtrip(client, services):
    """The settings page can set and clear the Discord token; it stays masked in responses."""
    r = await client.patch("/api/v1/settings", json={"discord_bot_token": "MTIz.abc-def_GHI"})
    assert r.status_code == 200
    by_key = {x["key"]: x for x in r.json()}
    assert by_key["discord_bot_token"]["secret"] is True
    assert services.settings.discord_bot_token == "MTIz.abc-def_GHI"

    r2 = await client.delete("/api/v1/settings/discord_bot_token")
    assert r2.status_code == 200
    assert services.settings.discord_bot_token is None
