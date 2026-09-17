"""OAuth plumbing for remote MCP servers: encrypted credential storage and the split redirect/callback flow."""
import asyncio

import pytest
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from openbot.mcp.oauth import DbTokenStorage, PendingFlows, load_or_create_key


def test_key_is_generated_once_and_kept_private(tmp_path):
    path = tmp_path / "k.key"
    k1 = load_or_create_key(None, path)
    assert path.is_file() and oct(path.stat().st_mode & 0o777) == "0o600"
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


async def test_pending_flow_can_fail_with_an_error_from_the_authorization_server():
    flows = PendingFlows()
    redirect, callback = flows.handlers("slack")
    waiter = asyncio.ensure_future(callback())
    await asyncio.sleep(0)
    await redirect("https://a/authorize?state=s1")
    assert flows.fail("s1", "access_denied") is True
    with pytest.raises(RuntimeError, match="access_denied"):
        await asyncio.wait_for(waiter, 1)
