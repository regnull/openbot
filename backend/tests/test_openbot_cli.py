"""Tests for the OpenBot terminal client.

All HTTP is mocked via ``httpx.MockTransport`` — no live server is required. The
``OpenBotClient`` is constructed with a prebuilt ``httpx.Client`` so the tests
exercise the request/parse logic without sockets, and ``stream_events`` is
monkeypatched for the ``watch`` path.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
from click.testing import CliRunner
from httpx import SyncByteStream

from openbot_cli import cli as cli_mod
from openbot_cli.client import GitHubIssuesClient, OpenBotClient, OpenBotClientError


class _SS(SyncByteStream):
    """Wrap a byte iterator as an httpx SyncByteStream for mocked streams."""

    def __init__(self, it):
        self._it = it

    def __iter__(self):
        return iter(self._it)


def _client(handler) -> OpenBotClient:
    # MockTransport responses aren't bound to their request, which makes httpx's
    # cookie extraction blow up ("unknown url type"). Bind it so the responses
    # behave like real ones — production code never hits this path. The injected
    # httpx.Client must carry base_url so relative paths resolve, mirroring how
    # OpenBotClient configures the client it builds itself.
    def _wrap(req: httpx.Request):
        resp = handler(req)
        resp.request = req
        return resp

    transport = httpx.MockTransport(_wrap)
    http_client = httpx.Client(base_url="http://test", transport=transport)
    return OpenBotClient(base_url="http://test", api_key="k", client=http_client)


def _json_response(payload, status=200):
    return httpx.Response(status, json=payload)


# ---------------------------------------------------------------------------
# Client unit tests
# ---------------------------------------------------------------------------

def test_list_threads_parses_payload():
    sample = [
        {
            "id": "thread_abc",
            "title": "Plan Rome trip",
            "last_message_at": "2026-10-20T10:00:00Z",
            "default_bot_handle": "eng",
            "active": True,
        }
    ]
    c = _client(lambda req: _json_response(sample) if req.url.path == "/api/v1/threads" else _json_response({}))
    assert c.list_threads() == sample


def test_get_thread_uses_limit_param():
    captured = {}

    def handler(req):
        if req.url.path.startswith("/api/v1/threads/") and req.method == "GET":
            captured["params"] = dict(req.url.params)
            return _json_response({"id": "t1", "messages": [], "participants": []})
        return _json_response({}, status=404)

    c = _client(handler)
    detail = c.get_thread("t1", limit=12)
    assert detail["id"] == "t1"
    assert captured["params"]["limit"] == "12"


def test_send_message_posts_body_and_returns_addressed():
    captured = {}

    def handler(req):
        if req.url.path.endswith("/messages") and req.method == "POST":
            captured["body"] = json.loads(req.content)
            return _json_response(
                {
                    "message": {"id": "m1", "sender_name": "you", "content": "hi", "created_at": "2026-10-20T10:00:00Z"},
                    "addressed": ["eng"],
                    "unaddressed": False,
                },
                status=201,
            )
        return _json_response({}, status=404)

    c = _client(handler)
    res = c.send_message("t1", "hi", to=["eng"], sender="you")
    assert captured["body"] == {"content": "hi", "to": ["eng"], "from": "you"}
    assert res["addressed"] == ["eng"]


def test_send_message_defaults_sender_to_human():
    captured = {}

    def handler(req):
        if req.url.path.endswith("/messages"):
            captured["body"] = json.loads(req.content)
            return _json_response({"message": {"id": "m1"}, "addressed": [], "unaddressed": True}, status=201)
        return _json_response({}, status=404)

    c = _client(handler)
    c.send_message("t1", "hi")
    assert "from" not in captured["body"]


def test_list_bots_and_runs():
    bots = [{"id": "b1", "handle": "eng", "name": "Engineer", "enabled": True, "active": True}]
    runs = [{"id": "r1", "actor_id": "a1", "thread_id": "t1", "status": "completed", "total_tokens": 10}]

    def handler(req):
        if req.url.path == "/api/v1/bots":
            return _json_response(bots)
        if req.url.path == "/api/v1/runs" and req.method == "GET":
            assert dict(req.url.params).get("thread_id") == "t1"
            return _json_response(runs)
        return _json_response({}, status=404)

    c = _client(handler)
    assert c.list_bots() == bots
    assert c.list_runs("t1") == runs


def test_health_probe_is_public_path():
    captured = {}

    def handler(req):
        captured["path"] = req.url.path
        return _json_response({"status": "ok"})
    c = _client(handler)
    c.ping()
    assert captured["path"] == "/api/v1/health"


def test_stream_events_yields_parsed_events():
    def sse_body() -> Iterator[bytes]:
        yield b": connected\n\n"
        yield b"event: message.created\ndata: " + json.dumps({"id": "m1"}).encode() + b"\n\n"
        yield b"data: " + json.dumps({"plain": True}).encode() + b"\n\n"

    captured = {}

    def handler(req):
        captured["path"] = req.url.path
        captured["params"] = dict(req.url.params)
        return httpx.Response(200, stream=_SS(sse_body()), headers={"content-type": "text/event-stream"})

    c = _client(handler)
    events = list(c.stream_events(thread_id="t1"))
    assert captured["path"] == "/api/v1/events"
    assert captured["params"]["thread_id"] == "t1"
    assert events[0] == {"event": "message.created", "id": "m1"}
    assert events[1] == {"event": "message", "plain": True}


def test_github_issues_calls_rest_api(monkeypatch):
    captured = {}

    class FakeResp:
        status_code = 200
        text = ""

        def json(self):
            return [{"number": 1, "title": "Bug", "state": "open", "labels": []}]

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return FakeResp()

    monkeypatch.setattr(httpx, "get", fake_get)
    issues = GitHubIssuesClient().list_issues(repo="regnull/openbot")
    assert captured["url"].endswith("/repos/regnull/openbot/issues")
    assert issues[0]["number"] == 1


def test_client_error_on_4xx():
    c = _client(lambda req: _json_response({"detail": "nope"}, status=404))
    with pytest.raises(OpenBotClientError):
        c.list_threads()


# ---------------------------------------------------------------------------
# CLI integration tests (CliRunner with injected client)
# ---------------------------------------------------------------------------

def _runner_with_client(c: OpenBotClient) -> CliRunner:
    runner = CliRunner()

    def invoke(args=None, **kwargs):
        # Callers pass a single command list (e.g. ["threads"]); forward it
        # directly to click so we don't accidentally nest it inside a tuple,
        # which would make click iterate over a list and raise
        # "unhashable type: 'list'" while parsing.
        kwargs.setdefault("obj", {})
        kwargs["obj"]["client"] = c
        kwargs["obj"]["base_url"] = c.base_url
        kwargs["obj"]["api_key"] = c.api_key
        return runner.invoke(cli_mod.cli, args, **kwargs)

    return invoke


def test_cli_threads_lists():
    c = _client(lambda req: _json_response([{"id": "t1", "title": "Hi", "default_bot_handle": "eng", "active": False}]))
    run = _runner_with_client(c)
    result = run(["threads"])
    assert result.exit_code == 0, result.output
    assert "t1" in result.output
    assert "@eng" in result.output


def test_cli_thread_shows_messages():
    detail = {
        "title": "Trip",
        "default_bot_handle": "eng",
        "participants": [],
        "has_more": False,
        "messages": [
            {"sender_name": "you", "created_at": "2026-10-20T10:00:00Z", "content": "hello", "mentions": ["eng"]}
        ],
    }
    c = _client(lambda req: _json_response(detail) if req.method == "GET" and "/threads/" in req.url.path else _json_response({}))
    result = _runner_with_client(c)(["thread", "t1"])
    assert result.exit_code == 0, result.output
    assert "hello" in result.output
    assert "@eng" in result.output


def test_cli_send_posts_and_reports_addressed():
    captured = {}

    def handler(req):
        if req.url.path.endswith("/messages"):
            captured["body"] = json.loads(req.content)
            return _json_response(
                {"message": {"id": "m1", "sender_name": "you", "created_at": "2026-10-20T10:00:00Z"},
                 "addressed": ["eng"], "unaddressed": False}, status=201)
        return _json_response({}, status=404)

    c = _client(handler)
    result = _runner_with_client(c)(["send", "t1", "do the thing", "--bot", "@eng"])
    assert result.exit_code == 0, result.output
    assert captured["body"]["to"] == ["eng"]
    assert "Addressed: @eng" in result.output


def test_cli_bots_and_runs():
    def handler(req):
        if req.url.path == "/api/v1/bots":
            return _json_response([{"id": "b1", "handle": "eng", "name": "Eng", "enabled": True, "active": True, "description": "d"}])
        if req.url.path == "/api/v1/runs":
            return _json_response([{"id": "r1", "actor_id": "a1", "thread_id": "t1", "status": "completed", "total_tokens": 5}])
        return _json_response({}, status=404)

    c = _client(handler)
    r1 = _runner_with_client(c)(["bots"])
    r2 = _runner_with_client(c)(["runs"])
    assert r1.exit_code == 0 and "eng" in r1.output
    assert r2.exit_code == 0 and "r1" in r2.output


def test_cli_connect_saves_and_pings(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg.json"
    captured = {}

    class _FakeClient:
        def __init__(self, base_url, api_key=None):
            captured["base_url"] = base_url
            captured["api_key"] = api_key

        def ping(self):
            captured["pinged"] = True
            return {"status": "ok"}

    monkeypatch.setattr(cli_mod, "OpenBotClient", _FakeClient)
    runner = CliRunner()
    result = runner.invoke(cli_mod.cli, ["connect", "https://example.test", "--api-key", "sek", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "Saved connection" in result.output
    assert "Connection OK" in result.output
    assert captured["base_url"] == "https://example.test"
    assert captured["api_key"] == "sek"
    assert captured["pinged"] is True
    saved = json.loads(cfg.read_text())
    assert saved["base_url"] == "https://example.test"
    assert saved["api_key"] == "sek"


def test_cli_connect_warns_when_server_unreachable(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg.json"

    class _FakeClient:
        def __init__(self, base_url, api_key=None):
            pass

        def ping(self):
            raise OpenBotClientError("GET /api/v1/health -> 500")

    monkeypatch.setattr(cli_mod, "OpenBotClient", _FakeClient)
    runner = CliRunner()
    result = runner.invoke(cli_mod.cli, ["connect", "https://down.test", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "Warning:" in result.output
    # Config is still saved even though the probe failed.
    assert json.loads(cfg.read_text())["base_url"] == "https://down.test"


def test_cli_issues_fetches_github(monkeypatch):
    class FakeResp:
        status_code = 200
        text = ""

        def json(self):
            return [{"number": 7, "title": "Broken thing", "state": "open", "labels": [{"name": "bug"}]}]

    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResp())
    c = _client(lambda req: _json_response({}))
    result = _runner_with_client(c)(["issues", "--repo", "regnull/openbot"])
    assert result.exit_code == 0, result.output
    assert "#7" in result.output
    assert "Broken thing" in result.output


def test_cli_thread_watch_streams(monkeypatch):
    detail = {
        "title": "Trip",
        "default_bot_handle": "eng",
        "participants": [],
        "has_more": False,
        "messages": [],
    }

    def sse_body():
        yield b"event: message.created\ndata: " + json.dumps({"sender_name": "eng", "created_at": "2026-10-20T10:00:00Z", "content": "on it"}).encode() + b"\n\n"

    def handler(req):
        # The `thread` command first fetches the detail (JSON), then opens the
        # SSE stream for `watch`; serve each with the right content type.
        if req.url.path.startswith("/api/v1/events"):
            return httpx.Response(200, stream=_SS(sse_body()), headers={"content-type": "text/event-stream"})
        return _json_response(detail)

    c = _client(handler)

    # Yield one event then stop, so `watch` exits; emulate Ctrl+C via StopIteration.
    original = c.stream_events

    def fake_stream(thread_id=None):
        for item in original(thread_id=thread_id):
            yield item
            break  # stop after the first event

    monkeypatch.setattr(c, "stream_events", fake_stream)
    result = _runner_with_client(c)(["thread", "t1", "watch"])
    assert result.exit_code == 0, result.output
    assert "on it" in result.output
