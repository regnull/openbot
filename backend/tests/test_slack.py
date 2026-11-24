"""Tests for Slack channel adapter.

Covers:
1. Slack event parsing (DM-only, bot/subtype echoes dropped)
2. Thread mapping: user creates thread on first message, stays on same thread
3. /new command creates a fresh thread
4. Events API webhook: signature validation, url_verification, re-announcement filter
5. Socket Mode client frame handling (inbound path, no real network)
6. Async delivery: bot messages in Slack threads are delivered via chat.postMessage
7. Config validation and settings API round-trip
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time

import pytest
from sqlalchemy import select

from openbot.channels.slack import (
    SlackDeliveryListener,
    SlackEvent,
    SlackSocketModeClient,
    _parse_channel_id_from_ref,
    deliver_to_slack,
    get_or_create_slack_actor,
    get_or_create_thread,
    handle_slack_command,
    parse_slack_event,
    process_slack_message,
    validate_slack_signature,
)
from openbot.db.models import Message, Thread

# ---------------------------------------------------------------------------
# Slack event parsing tests
# ---------------------------------------------------------------------------


def _dm_event_payload(text: str = "Hello bot", channel: str = "D0123456789",
                      user: str = "U0123456789", bot_id: str | None = None,
                      subtype: str | None = None) -> dict:
    """A raw Slack `event` object shaped like an Events API / Socket Mode message.im event."""
    event = {
        "type": "message",
        "channel": channel,
        "user": user,
        "text": text,
        "ts": "1700000000.000100",
        "event_ts": "1700000000.000100",
    }
    if bot_id:
        event["bot_id"] = bot_id
    if subtype:
        event["subtype"] = subtype
    return event


class TestParseSlackEvent:
    def test_parse_basic_dm(self):
        event = parse_slack_event(_dm_event_payload())
        assert event is not None
        assert event.channel_id == "D0123456789"
        assert event.user_id == "U0123456789"
        assert event.text == "Hello bot"
        assert event.is_command is False

    def test_parse_command(self):
        event = parse_slack_event(_dm_event_payload("/new"))
        assert event is not None
        assert event.is_command is True
        assert event.command == "new"

    def test_channel_message_returns_none(self):
        """The bot must never answer in shared channels, only DMs."""
        assert parse_slack_event(_dm_event_payload(channel="C0123456789")) is None

    def test_bot_echo_returns_none(self):
        assert parse_slack_event(_dm_event_payload(bot_id="B0123456789")) is None

    def test_subtype_echo_returns_none(self):
        """Edits and thread replies re-announce the message; answering those loops."""
        assert parse_slack_event(_dm_event_payload(subtype="thread_broadcast")) is None

    def test_empty_text_returns_none(self):
        assert parse_slack_event(_dm_event_payload("")) is None

    def test_non_message_event_returns_none(self):
        assert parse_slack_event({"type": "reaction_added"}) is None


# ---------------------------------------------------------------------------
# Signature validation tests
# ---------------------------------------------------------------------------


def _sign(secret: str, timestamp: str, body: bytes) -> str:
    base = f"v0:{timestamp}:{body.decode()}"
    return "v0=" + hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()


def test_validate_slack_signature_valid():
    secret = "8f7421exxxxxxxxxxxxxxx"
    ts = str(int(time.time()))
    body = json.dumps({"type": "event_callback"}).encode()
    assert validate_slack_signature(secret, ts, body, _sign(secret, ts, body)) is True


def test_validate_slack_signature_wrong_secret():
    ts = str(int(time.time()))
    body = b"{}"
    sig = _sign("secret-a", ts, body)
    assert validate_slack_signature("secret-b", ts, body, sig) is False


def test_validate_slack_signature_stale_timestamp():
    secret = "s3cr3t"
    ts = str(int(time.time()) - 3600)  # an hour old: replay
    body = b"{}"
    assert validate_slack_signature(secret, ts, body, _sign(secret, ts, body)) is False


def test_validate_slack_signature_malformed():
    assert validate_slack_signature("s", "", b"{}", "v0=abc") is False
    assert validate_slack_signature("s", "notanumber", b"{}", "v0=abc") is False
    assert validate_slack_signature("s", str(int(time.time())), b"{}", "badprefix") is False


# ---------------------------------------------------------------------------
# Actor and thread mapping tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_create_slack_actor_creates_new(services):
    async with services.session_factory() as session:
        actor = await get_or_create_slack_actor(session, "U0AAAAAAA")
        assert actor.handle == "sl_U0AAAAAAA"
        assert actor.kind == "external"
        assert actor.name == "Slack U0AAAAAAA"


@pytest.mark.asyncio
async def test_get_or_create_thread_creates_new(services):
    async with services.session_factory() as session:
        actor = await get_or_create_slack_actor(session, "U0BBBBBBB")
        thread = await get_or_create_thread(services, session, "D0BBBBBBB", actor)
        assert thread.external_ref == "slack:D0BBBBBBB"
        assert thread.kind == "chat"


@pytest.mark.asyncio
async def test_get_or_create_thread_returns_existing(services):
    async with services.session_factory() as session:
        actor = await get_or_create_slack_actor(session, "U0CCCCCCC")
        t1 = await get_or_create_thread(services, session, "D0CCCCCCC", actor)
        t2 = await get_or_create_thread(services, session, "D0CCCCCCC", actor)
        assert t1.id == t2.id


# ---------------------------------------------------------------------------
# Command tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_new_command_creates_fresh_thread(services):
    async with services.session_factory() as session:
        actor = await get_or_create_slack_actor(session, "U0DDDDDDD")
        old = await get_or_create_thread(services, session, "D0DDDDDDD", actor)
        old_id = old.id

        event = SlackEvent(
            event_id="1", channel_id="D0DDDDDDD", user_id="U0DDDDDDD",
            text="/new", is_command=True, command="new",
        )
        response = await handle_slack_command(services, session, event, actor)
        assert "New conversation" in response

        fresh = (
            await session.execute(
                select(Thread).where(Thread.external_ref == "slack:D0DDDDDDD")
            )
        ).scalar_one()
        assert fresh.id != old_id


@pytest.mark.asyncio
async def test_handle_help_command_returns_response(services):
    async with services.session_factory() as session:
        actor = await get_or_create_slack_actor(session, "U0EEEEEEE")
        event = SlackEvent(
            event_id="1", channel_id="D0EEEEEEE", user_id="U0EEEEEEE",
            text="/help", is_command=True, command="help",
        )
        response = await handle_slack_command(services, session, event, actor)
        assert "/new" in response


# ---------------------------------------------------------------------------
# process_slack_message tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_command_returns_response(services):
    async with services.session_factory() as session:
        event = SlackEvent(
            event_id="1", channel_id="D0FFFFFFF", user_id="U0FFFFFFF",
            text="/start", is_command=True, command="start",
        )
        response = await process_slack_message(services, session, event)
        assert "Welcome" in response


@pytest.mark.asyncio
async def test_process_message_posts_to_thread(services):
    """A fake inbound DM reaches the agent pipeline: actor + thread message created."""
    async with services.session_factory() as session:
        event = SlackEvent(
            event_id="1", channel_id="D10000001", user_id="U10000001",
            text="Hello there", is_command=False, command=None,
        )
        result = await process_slack_message(services, session, event)
        assert result is None  # bot reply arrives asynchronously via the listener
        await session.commit()

    async with services.session_factory() as session:
        thread = (
            await session.execute(
                select(Thread).where(Thread.external_ref == "slack:D10000001")
            )
        ).scalar_one()
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
async def test_deliver_to_slack_no_token(services):
    result = await deliver_to_slack(services, "D10000002", "test")
    assert result is False


def test_parse_channel_id_from_ref_valid():
    assert _parse_channel_id_from_ref("slack:D0123456789") == "D0123456789"


def test_parse_channel_id_from_ref_invalid():
    assert _parse_channel_id_from_ref("slack:") is None
    assert _parse_channel_id_from_ref("telegram:123") is None
    assert _parse_channel_id_from_ref("") is None
    assert _parse_channel_id_from_ref(None) is None


# ---------------------------------------------------------------------------
# SlackDeliveryListener tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delivery_listener_delivers_bot_message(services):
    """When a bot posts in a Slack thread, the listener delivers to Slack."""
    async with services.session_factory() as session:
        actor = await get_or_create_slack_actor(session, "U20000001")
        thread = await get_or_create_thread(services, session, "D20000001", actor)
        thread_id = thread.id
        await session.commit()

    delivered: list[tuple[str, str]] = []

    async def mock_deliver(services, channel_id, text):
        delivered.append((channel_id, text))
        return True

    import openbot.channels.slack as sl_mod
    original = sl_mod.deliver_to_slack
    sl_mod.deliver_to_slack = mock_deliver
    try:
        listener = SlackDeliveryListener(services)
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
        assert delivered[0] == ("D20000001", "Hello from the bot!")
    finally:
        sl_mod.deliver_to_slack = original


@pytest.mark.asyncio
async def test_delivery_listener_ignores_human_messages(services):
    async with services.session_factory() as session:
        actor = await get_or_create_slack_actor(session, "U20000002")
        thread = await get_or_create_thread(services, session, "D20000002", actor)
        thread_id = thread.id
        await session.commit()

    delivered: list[tuple[str, str]] = []

    async def mock_deliver(services, channel_id, text):
        delivered.append((channel_id, text))
        return True

    import openbot.channels.slack as sl_mod
    original = sl_mod.deliver_to_slack
    sl_mod.deliver_to_slack = mock_deliver
    try:
        listener = SlackDeliveryListener(services)
        await listener.start()
        await asyncio.sleep(0.05)

        await services.bus.publish(
            "message.created",
            thread_id,
            {"sender_kind": "external", "sender_name": "User", "content": "Hello from user"},
        )

        await asyncio.sleep(0.3)
        await listener.stop()
        assert len(delivered) == 0
    finally:
        sl_mod.deliver_to_slack = original


@pytest.mark.asyncio
async def test_delivery_listener_start_stop_idempotent(services):
    listener = SlackDeliveryListener(services)
    await listener.start()
    await listener.start()
    await listener.stop()
    await listener.stop()


# ---------------------------------------------------------------------------
# Socket Mode client tests (inbound path, no real network)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_socket_mode_client_start_stop(services):
    client = SlackSocketModeClient(services)
    await client.start()
    assert client._running is True
    await client.stop()
    assert client._running is False
    await client.stop()


class _FakeSocket:
    """Stands in for the Socket Mode websocket: records acks, answers nothing else."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))


@pytest.mark.asyncio
async def test_socket_mode_frame_processes_dm_and_command(services):
    """A fake events_api frame reaches the handler; /start gets an immediate reply."""
    client = SlackSocketModeClient(services)
    client._ws = _FakeSocket()

    delivered: list[tuple[str, str]] = []

    async def mock_deliver(services, channel_id, text):
        delivered.append((channel_id, text))
        return True

    import openbot.channels.slack as sl_mod
    original = sl_mod.deliver_to_slack
    sl_mod.deliver_to_slack = mock_deliver
    try:
        frame = json.dumps({
            "type": "events_api",
            "id": "env-1",
            "payload": {
                "type": "event_callback",
                "event": _dm_event_payload("/start", channel="D30000001"),
            },
        })
        await client._handle_frame(frame)

        acks = [m for m in client._ws.sent if m.get("id") == "env-1"]  # type: ignore[union-attr]
        assert acks and acks[0]["type"] == "ack"
        assert len(delivered) == 1
        assert delivered[0][0] == "D30000001"
        assert "Welcome" in delivered[0][1]

        # A regular DM frame posts to a thread and returns without direct delivery.
        frame2 = json.dumps({
            "type": "events_api",
            "id": "env-2",
            "payload": {
                "type": "event_callback",
                "event": _dm_event_payload("hi", channel="D30000002"),
            },
        })
        await client._handle_frame(frame2)
        assert len(delivered) == 1

        async with services.session_factory() as session:
            thread = (
                await session.execute(
                    select(Thread).where(Thread.external_ref == "slack:D30000002")
                )
            ).scalar_one_or_none()
            assert thread is not None
    finally:
        sl_mod.deliver_to_slack = original


@pytest.mark.asyncio
async def test_socket_mode_skips_reannounced_message(services):
    """ts != event_ts (edit or reply to an answered message) must not start a second run."""
    client = SlackSocketModeClient(services)
    client._ws = _FakeSocket()

    event = _dm_event_payload("Hello there", channel="D30000003")
    event["ts"] = "1700000999.000200"  # re-announcement bumps ts
    frame = json.dumps({
        "type": "events_api", "id": "env-3",
        "payload": {"type": "event_callback", "event": event},
    })
    await client._handle_frame(frame)

    async with services.session_factory() as session:
        thread = (
            await session.execute(
                select(Thread).where(Thread.external_ref == "slack:D30000003")
            )
        ).scalar_one_or_none()
        assert thread is None


@pytest.mark.asyncio
async def test_socket_mode_pings_are_acked(services):
    client = SlackSocketModeClient(services)
    client._ws = _FakeSocket()
    await client._handle_frame(json.dumps({"type": "ping", "id": "env-p"}))
    assert client._ws.sent[-1] == {"type": "pong", "id": "env-p"}  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# HTTP endpoint tests (webhook transport)
# ---------------------------------------------------------------------------


class TestEventsEndpoint:
    @pytest.mark.asyncio
    async def test_events_returns_200_for_valid_message(self, client):
        payload = {
            "type": "event_callback",
            "event": _dm_event_payload("Hello bot", channel="D40000001"),
        }
        resp = await client.post("/api/v1/channels/slack/events", json=payload)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_events_answers_url_verification(self, client):
        resp = await client.post(
            "/api/v1/channels/slack/events",
            json={"type": "url_verification", "challenge": "abc123"},
        )
        assert resp.status_code == 200
        assert resp.json()["challenge"] == "abc123"

    @pytest.mark.asyncio
    async def test_events_rejects_invalid_json(self, client):
        resp = await client.post(
            "/api/v1/channels/slack/events",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_events_rejects_bad_signature_when_secret_configured(self, client, services):
        services.settings = services.settings.model_copy(
            update={"slack_signing_secret": "test-signing-secret"}
        )
        payload = {
            "type": "event_callback",
            "event": _dm_event_payload("Hello", channel="D40000002"),
        }
        resp = await client.post("/api/v1/channels/slack/events", json=payload)
        assert resp.status_code == 403
        assert "signature" in resp.text.lower()

    @pytest.mark.asyncio
    async def test_events_accepts_valid_signature(self, client, services):
        secret = "test-signing-secret-2"
        services.settings = services.settings.model_copy(update={"slack_signing_secret": secret})
        payload = {
            "type": "event_callback",
            "event": _dm_event_payload("/start", channel="D40000003"),
        }
        body = json.dumps(payload).encode()
        ts = str(int(time.time()))
        resp = await client.post(
            "/api/v1/channels/slack/events",
            content=body,
            headers={
                "content-type": "application/json",
                "X-Slack-Request-Timestamp": ts,
                "X-Slack-Signature": _sign(secret, ts, body),
            },
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_status_endpoint(self, client, services):
        resp = await client.get("/api/v1/channels/slack/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["configured"] is False  # no token in test
        assert body["transport"] == "socket_mode"


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


def test_slack_config_empty_tokens_mean_unset():
    from openbot.config import Settings
    s = Settings(slack_bot_token="", slack_app_token="", slack_signing_secret="", _env_file=None)
    assert s.slack_bot_token is None
    assert s.slack_app_token is None
    assert s.slack_signing_secret is None


def test_slack_config_transport_default():
    from openbot.config import Settings
    s = Settings(_env_file=None)
    assert s.slack_transport == "socket_mode"


def test_slack_config_transport_invalid():
    from pydantic import ValidationError

    from openbot.config import Settings
    with pytest.raises(ValidationError):
        Settings(slack_transport="carrier-pigeon", _env_file=None)


@pytest.mark.asyncio
async def test_settings_api_slack_tokens_roundtrip(client, services):
    """The settings page can set Slack tokens; they stay masked and format-checked."""
    r = await client.patch("/api/v1/settings", json={
        "slack_bot_token": "xoxb-test-token-value",
        "slack_app_token": "xapp-test-token-value",
    })
    assert r.status_code == 200
    by_key = {x["key"]: x for x in r.json()}
    assert by_key["slack_bot_token"]["secret"] is True
    assert by_key["slack_bot_token"]["value"] == "••••••••"
    assert services.settings.slack_bot_token == "xoxb-test-token-value"
    assert services.settings.slack_app_token == "xapp-test-token-value"

    r2 = await client.patch("/api/v1/settings", json={"slack_bot_token": "wrong-prefix-"})
    assert r2.status_code == 422
    assert services.settings.slack_bot_token == "xoxb-test-token-value"

    r3 = await client.delete("/api/v1/settings/slack_bot_token")
    assert r3.status_code == 200
    assert services.settings.slack_bot_token is None
