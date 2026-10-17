"""OAuth plumbing for remote MCP servers: encrypted credential storage and the split redirect/callback flow."""
import asyncio
import sys

import pytest
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from openbot.mcp.oauth import (
    CALLBACK_PATH,
    DbTokenStorage,
    PendingFlows,
    build_oauth_provider,
    load_or_create_key,
)


def test_key_is_generated_once_and_kept_private(tmp_path):
    path = tmp_path / "k.key"
    k1 = load_or_create_key(None, path)
    assert path.is_file()
    if sys.platform != "win32":                                        # Windows has no POSIX mode bits
        assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert load_or_create_key(None, path) == k1                      # stable across restarts
    assert load_or_create_key("explicit-key-wins", path) == "explicit-key-wins"


async def test_credentials_round_trip_encrypted_at_rest(services, tmp_path):
    from sqlalchemy import select

    from openbot.db.models import McpCredential
    key = load_or_create_key(None, tmp_path / "k.key")
    store = DbTokenStorage(services.session_factory, server="linear", key=key)
    assert await store.get_tokens() is None and await store.get_client_info() is None
    await store.set_client_info(OAuthClientInformationFull(client_id="cid", redirect_uris=["http://127.0.0.1:8000/mcp/oauth/callback"]))
    await store.set_tokens(OAuthToken(access_token="secret-access", refresh_token="secret-refresh"))
    assert (await store.get_tokens()).access_token == "secret-access"
    assert (await store.get_client_info()).client_id == "cid"
    async with services.session_factory() as s:
        row = (await s.execute(select(McpCredential).where(McpCredential.server == "linear"))).scalar_one()
    assert "secret-access" not in row.tokens and "secret-refresh" not in row.tokens and "cid" not in row.client_info
    await store.clear()
    assert await store.get_tokens() is None


async def test_refresh_response_without_refresh_token_preserves_existing_grant(services, tmp_path):
    key = load_or_create_key(None, tmp_path / "k.key")
    store = DbTokenStorage(services.session_factory, server="linear", key=key)
    await store.set_tokens(OAuthToken(access_token="old-access", refresh_token="durable-refresh"))

    await store.set_tokens(OAuthToken(access_token="new-access", expires_in=3600))

    tokens = await store.get_tokens()
    assert tokens is not None
    assert tokens.access_token == "new-access"
    assert tokens.refresh_token == "durable-refresh"


async def test_pending_flow_records_the_url_and_the_callback_resolves_it():
    flows = PendingFlows()
    redirect, callback = flows.handlers("linear")
    waiter = asyncio.ensure_future(callback())
    await asyncio.sleep(0)
    await redirect("https://auth.example/authorize?client_id=x&state=abc123&code_challenge=y")
    assert flows.authorization_url("linear") == "https://auth.example/authorize?client_id=x&state=abc123&code_challenge=y"
    assert flows.server_for_state("abc123") == "linear"
    assert flows.complete("abc123", code="the-code") is True
    assert await asyncio.wait_for(waiter, 1) == ("the-code", "abc123")
    assert flows.authorization_url("linear") is None                 # consumed
    assert flows.complete("unknown", code="x") is False



def test_oauth_provider_uses_configured_application_origin_for_callback(services, tmp_path):
    key = load_or_create_key(None, tmp_path / "k.key")
    store = DbTokenStorage(services.session_factory, server="linear", key=key)
    provider = build_oauth_provider(
        "https://mcp.linear.app/mcp", "https://openbot.example.test", store, PendingFlows(), "linear"
    )
    assert [str(uri) for uri in provider.context.client_metadata.redirect_uris] == [
        f"https://openbot.example.test{CALLBACK_PATH}"
    ]


async def test_pending_flow_can_fail_with_an_error_from_the_authorization_server():
    flows = PendingFlows()
    redirect, callback = flows.handlers("slack")
    waiter = asyncio.ensure_future(callback())
    await asyncio.sleep(0)
    await redirect("https://a/authorize?state=s1")
    assert flows.fail("s1", "access_denied") is True
    with pytest.raises(RuntimeError, match="access_denied"):
        await asyncio.wait_for(waiter, 1)


async def _stale_credentials(services, tmp_path, **token_args):
    key = load_or_create_key(None, tmp_path / "k.key")
    store = DbTokenStorage(services.session_factory, server="linear", key=key, url="https://mcp.example/mcp")
    await store.set_client_info(OAuthClientInformationFull(client_id="cid", redirect_uris=["http://127.0.0.1:8001/cb"]))
    await store.set_tokens(OAuthToken(access_token="stale", refresh_token="refresh-1", **token_args))
    return store


def _fake_server(seen: list[str]):
    import json

    import httpx

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        if request.url.path == "/token":
            assert b"grant_type=refresh_token" in request.content and b"refresh_token=refresh-1" in request.content
            return httpx.Response(200, json={"access_token": "fresh", "token_type": "Bearer", "expires_in": 86100,
                                             "refresh_token": "refresh-2"})
        if request.headers.get("Authorization") == "Bearer fresh":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(401, headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
                              content=json.dumps({"error": "invalid_token"}))

    return httpx.MockTransport(handle)


async def test_a_restart_refreshes_an_expired_token_instead_of_asking_for_authorization(services, tmp_path):
    import time

    import httpx

    from openbot.db.models import McpCredential
    store = await _stale_credentials(services, tmp_path, expires_in=86100)
    async with services.session_factory() as s:          # issued yesterday, like Linear's 24h token
        row = await s.get(McpCredential, "linear")
        row.tokens = store._fernet.encrypt(
            f'{{"access_token":"stale","refresh_token":"refresh-1","expires_in":86100,"expires_at":{time.time() - 3600}}}'.encode()
        ).decode()
        await s.commit()

    provider = build_oauth_provider("https://mcp.example/mcp", "http://127.0.0.1:8001", store, PendingFlows(), "linear",
                                    allow=lambda: False)            # boot: no browser allowed
    seen: list[str] = []
    async with httpx.AsyncClient(transport=_fake_server(seen), auth=provider) as client:
        r = await client.get("https://mcp.example/mcp")
    assert r.status_code == 200
    assert seen == ["POST /token", "GET /mcp"]                       # refreshed first, never sent the stale token
    stored = await store.get_tokens()
    assert stored.access_token == "fresh" and stored.refresh_token == "refresh-2"
    await store.get_tokens()
    assert store.loaded_expiry > time.time() + 86000


async def test_rows_saved_before_expires_at_existed_count_from_their_last_update(services, tmp_path):
    from datetime import timedelta

    from openbot.db.models import McpCredential, utcnow
    store = await _stale_credentials(services, tmp_path, expires_in=86100)
    async with services.session_factory() as s:
        row = await s.get(McpCredential, "linear")
        row.tokens = store._fernet.encrypt(b'{"access_token":"stale","refresh_token":"refresh-1","expires_in":86100}').decode()
        row.updated_at = utcnow() - timedelta(days=1)
        await s.commit()
        updated = row.updated_at
    assert (await store.get_tokens()).access_token == "stale"
    assert store.loaded_expiry == pytest.approx(updated.timestamp() + 86100)


def test_an_authorization_request_wrapped_by_a_task_group_is_recognised():
    from openbot.mcp.manager import _only
    from openbot.mcp.oauth import AuthorizationRequired
    nested = ExceptionGroup("tg", [ExceptionGroup("inner", [AuthorizationRequired("linear")])])
    assert _only(nested, AuthorizationRequired)
    assert not _only(ExceptionGroup("tg", [RuntimeError("x")]), AuthorizationRequired)
    # A real failure next to it is that failure, not a clean needs_auth.
    assert not _only(ExceptionGroup("tg", [AuthorizationRequired("linear"), OSError("tls")]), AuthorizationRequired)


async def _set_raw_tokens(services, store, raw: dict):
    import json

    from openbot.db.models import McpCredential
    async with services.session_factory() as s:
        row = await s.get(McpCredential, "linear")
        row.tokens = store._fernet.encrypt(json.dumps(raw).encode()).decode()
        await s.commit()


async def test_a_token_without_a_lifetime_is_used_as_is(services, tmp_path):
    import httpx
    store = await _stale_credentials(services, tmp_path)               # no expires_in at all
    provider = build_oauth_provider("https://mcp.example/mcp", "http://127.0.0.1:8001", store, PendingFlows(), "linear",
                                    allow=lambda: False)
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        return httpx.Response(200 if request.headers.get("Authorization") == "Bearer stale" else 401)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), auth=provider) as client:
        assert (await client.get("https://mcp.example/mcp")).status_code == 200
    assert seen == ["GET /mcp"]                                        # no forced refresh


async def test_a_failed_refresh_is_not_retried_on_every_request(services, tmp_path):
    import time

    import httpx

    from openbot.mcp.oauth import AuthorizationRequired
    store = await _stale_credentials(services, tmp_path, expires_in=60)
    await _set_raw_tokens(services, store, {"access_token": "stale", "refresh_token": "revoked",
                                            "expires_in": 60, "expires_at": time.time() - 10})
    provider = build_oauth_provider("https://mcp.example/mcp", "http://127.0.0.1:8001", store, PendingFlows(), "linear",
                                    allow=lambda: False)
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        if request.url.path == "/token":
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(401)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), auth=provider) as client:
        for _ in range(2):
            with pytest.raises(AuthorizationRequired):
                await client.get("https://mcp.example/mcp")
    assert seen.count("POST /token") == 1


async def test_the_refresh_uses_the_token_endpoint_remembered_from_authorization(services, tmp_path):
    import time

    import httpx
    store = await _stale_credentials(services, tmp_path, expires_in=60)
    await _set_raw_tokens(services, store, {
        "access_token": "stale", "refresh_token": "refresh-1", "expires_in": 60, "expires_at": time.time() - 10,
        "oauth_metadata": {"issuer": "https://auth.example/", "authorization_endpoint": "https://auth.example/authorize",
                           "token_endpoint": "https://auth.example/oauth/token"}})
    provider = build_oauth_provider("https://mcp.example/mcp", "http://127.0.0.1:8001", store, PendingFlows(), "linear",
                                    allow=lambda: False)
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.host}{request.url.path}")
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "fresh", "token_type": "Bearer", "expires_in": 3600})
        return httpx.Response(200 if request.headers.get("Authorization") == "Bearer fresh" else 401)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), auth=provider) as client:
        assert (await client.get("https://mcp.example/mcp")).status_code == 200
    assert seen == ["POST auth.example/oauth/token", "GET mcp.example/mcp"]
    await store.get_tokens()
    assert store.loaded_metadata is not None and str(store.loaded_metadata.token_endpoint) == "https://auth.example/oauth/token"


async def test_two_providers_for_one_server_refresh_once(services, tmp_path):
    import asyncio
    import time

    import httpx
    store = await _stale_credentials(services, tmp_path, expires_in=60)
    await _set_raw_tokens(services, store, {"access_token": "stale", "refresh_token": "refresh-1",
                                            "expires_in": 60, "expires_at": time.time() - 10})
    refreshes = 0

    async def handle(request: httpx.Request) -> httpx.Response:
        nonlocal refreshes
        if request.url.path == "/token":
            refreshes += 1
            await asyncio.sleep(0.05)
            return httpx.Response(200, json={"access_token": "fresh", "token_type": "Bearer", "expires_in": 3600,
                                             "refresh_token": "refresh-2"})
        return httpx.Response(200 if request.headers.get("Authorization") == "Bearer fresh" else 401)

    async def call():
        provider = build_oauth_provider("https://mcp.example/mcp", "http://127.0.0.1:8001", store, PendingFlows(),
                                        "linear", allow=lambda: False)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle), auth=provider) as client:
            return (await client.get("https://mcp.example/mcp")).status_code

    assert await asyncio.gather(call(), call()) == [200, 200]
    assert refreshes == 1


async def test_a_credential_blob_that_is_not_an_object_reads_as_absent(services, tmp_path):
    store = await _stale_credentials(services, tmp_path)
    from openbot.db.models import McpCredential
    async with services.session_factory() as s:
        row = await s.get(McpCredential, "linear")
        row.tokens = store._fernet.encrypt(b'["not", "an", "object"]').decode()
        await s.commit()
    assert await store.get_tokens() is None
