"""OAuth for remote MCP servers, split across HTTP requests the way a web app needs it.

The MCP SDK's `OAuthClientProvider` runs the whole OAuth 2.1 flow (discovery, registration, PKCE,
token exchange, refresh) as an httpx auth and asks the application for three things: somewhere to
keep credentials, a way to send the user to the authorization URL, and a way to receive the
callback. Here those are a Fernet-encrypted table, a pending-flow record the Settings UI reads the
URL from, and a future the public callback endpoint resolves.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import weakref
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

import anyio
from cryptography.fernet import Fernet, InvalidToken
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
    OAuthToken,
)
from sqlalchemy.ext.asyncio import async_sessionmaker

from openbot.db.models import McpCredential, utcnow
from openbot.runtime.secrets import load_or_create_key

log = logging.getLogger(__name__)

CALLBACK_PATH = "/api/v1/mcp/oauth/callback"   # on the public router: the browser arrives without an API key
# Refresh this long before the stored expiry, so a request in flight does not reach the server just after it.
EXPIRY_MARGIN = 60.0


class AuthorizationRequired(RuntimeError):
    """The server wants the operator to authorize, but nobody is there to open a browser (boot, a
    reconnect, or a bot's tool call). Fail fast so the caller can report needs_auth or a tool error
    instead of waiting on a callback that cannot arrive."""


class DbTokenStorage:
    """`mcp.client.auth.TokenStorage` over the mcp_credentials table, one row per server, encrypted."""

    def __init__(self, session_factory: async_sessionmaker, server: str, key: str, url: str | None = None) -> None:
        self._sf = session_factory
        self.server = server
        self.url = url
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
        # Filled by the last get_tokens(), for StoredExpiryOAuthProvider: when the access token expires
        # (Unix time; None if the server gave no lifetime) and the authorization server's metadata.
        self.loaded_expiry: float | None = None
        self.loaded_metadata: OAuthMetadata | None = None

    def _enc(self, obj) -> str:
        return self._enc_raw(obj.model_dump(mode="json", exclude_none=True))

    def _enc_raw(self, raw: dict) -> str:
        return self._fernet.encrypt(json.dumps(raw).encode()).decode()

    def _dec_raw(self, blob: str | None) -> dict | None:
        if not blob:
            return None
        try:
            raw = json.loads(self._fernet.decrypt(blob.encode()))
            if not isinstance(raw, dict):
                raise TypeError("not a JSON object")
            return raw
        except (InvalidToken, ValueError, TypeError) as e:
            # A rotated key or a corrupt row: behave as "no credentials" so the operator can re-authorize,
            # rather than failing every connect.
            log.warning("MCP credentials for %s cannot be read (%s); treating as absent", self.server, type(e).__name__)
            return None

    def _dec(self, blob: str | None, model):
        raw = self._dec_raw(blob)
        try:
            return model.model_validate(raw) if raw is not None else None
        except ValueError as e:
            log.warning("MCP credentials for %s cannot be read (%s); treating as absent", self.server, type(e).__name__)
            return None

    async def _row(self, session) -> McpCredential:
        row = await session.get(McpCredential, self.server)
        if row is None:
            row = McpCredential(server=self.server, resource_url=self.url, client_info=None, tokens=None, updated_at=utcnow())
            session.add(row)
        return row

    async def _current_row(self, session) -> McpCredential | None:
        """The stored row, unless it was issued for a different server URL: credentials are bound to the
        resource they were granted for, so re-pointing a config name at another host must never send
        the old bearer token there. Such a row is dropped."""
        row = await session.get(McpCredential, self.server)
        if row is not None and self.url and row.resource_url and row.resource_url != self.url:
            log.warning("MCP server %s now points at %s; dropping credentials issued for %s", self.server, self.url, row.resource_url)
            await session.delete(row)
            await session.commit()
            return None
        return row

    # The tokens blob holds the OAuthToken fields plus two of ours: `expires_at` (OAuthToken only has
    # the relative `expires_in`) and `oauth_metadata` (where the token endpoint is, which a refresh
    # right after a restart needs before any discovery has run).
    _EXTRA = ("expires_at", "oauth_metadata")

    def _split(self, raw: dict | None) -> tuple[OAuthToken | None, dict]:
        if raw is None:
            return None, {}
        extra = {k: raw.pop(k) for k in self._EXTRA if k in raw}
        try:
            return OAuthToken.model_validate(raw), extra
        except ValueError as e:
            log.warning("MCP credentials for %s cannot be read (%s); treating as absent", self.server, type(e).__name__)
            return None, {}

    async def get_tokens(self) -> OAuthToken | None:
        async with self._sf() as s:
            row = await self._current_row(s)
            tokens, extra = self._split(self._dec_raw(row.tokens if row else None))
        self.loaded_expiry = extra.get("expires_at")
        if tokens is not None and self.loaded_expiry is None and tokens.expires_in is not None:
            # Written before expires_at was stored: the tokens were the row's last change.
            self.loaded_expiry = row.updated_at.timestamp() + int(tokens.expires_in)
        try:
            self.loaded_metadata = OAuthMetadata.model_validate(extra["oauth_metadata"]) if extra.get("oauth_metadata") else None
        except ValueError:
            self.loaded_metadata = None
        return tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        async with self._sf() as s:
            row = await self._row(s)
            previous, extra = self._split(self._dec_raw(row.tokens))
            if tokens.refresh_token is None and previous and previous.refresh_token:
                # RFC 6749 allows a refresh response to omit refresh_token. Keep the
                # existing grant so a later restart can refresh the new access token.
                tokens = tokens.model_copy(update={"refresh_token": previous.refresh_token})
            raw = tokens.model_dump(mode="json", exclude_none=True)
            if tokens.expires_in is not None:
                raw["expires_at"] = time.time() + int(tokens.expires_in)
            if extra.get("oauth_metadata"):
                raw["oauth_metadata"] = extra["oauth_metadata"]
            row.tokens, row.resource_url, row.updated_at = self._enc_raw(raw), self.url or row.resource_url, utcnow()
            await s.commit()

    async def set_oauth_metadata(self, metadata: OAuthMetadata) -> None:
        """Remember the authorization server's metadata with the tokens it issued."""
        async with self._sf() as s:
            row = await self._current_row(s)
            raw = self._dec_raw(row.tokens if row else None)
            if raw is None:
                return
            raw["oauth_metadata"] = metadata.model_dump(mode="json", exclude_none=True)
            row.tokens = self._enc_raw(raw)
            await s.commit()

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        async with self._sf() as s:
            row = await self._current_row(s)
            return self._dec(row.client_info if row else None, OAuthClientInformationFull)

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        async with self._sf() as s:
            row = await self._row(s)
            row.client_info, row.resource_url, row.updated_at = self._enc(client_info), self.url or row.resource_url, utcnow()
            await s.commit()

    async def clear(self) -> None:
        async with self._sf() as s:
            row = await s.get(McpCredential, self.server)
            if row is not None:
                await s.delete(row)
                await s.commit()


@dataclass
class _Flow:
    server: str
    url: str | None = None
    state: str | None = None
    future: asyncio.Future | None = None
    consumed: bool = False


@dataclass
class PendingFlows:
    """The authorization flows waiting on a browser, keyed by server and by OAuth `state`.

    The SDK calls `redirect_handler(url)` when the user must authorize and then awaits
    `callback_handler()` for `(code, state)`. In a CLI those open a browser and listen on localhost;
    here the URL is recorded for the Settings UI to open, and the public callback endpoint resolves
    the future with the code the authorization server sent back.
    """
    _by_server: dict[str, _Flow] = field(default_factory=dict)
    _by_state: dict[str, _Flow] = field(default_factory=dict)

    def handlers(self, server: str, allow: Callable[[], bool] | None = None,
                 ) -> tuple[Callable[[str], Awaitable[None]], Callable[[], Awaitable[tuple[str, str | None]]]]:
        """`allow` says whether a browser flow may start right now. The SDK keeps these handlers for the
        life of the session, so a 401 long after connect (expired token, revoked grant) would otherwise
        park a bot's tool call on a callback nobody is waiting to answer."""
        flow = _Flow(server=server)

        async def redirect(url: str) -> None:
            if allow is not None and not allow():
                raise AuthorizationRequired(f"MCP server {server} needs authorization; connect it from Settings")
            self._by_server[server] = flow
            flow.url = url
            flow.state = (parse_qs(urlparse(url).query).get("state") or [None])[0]
            if flow.state:
                self._by_state[flow.state] = flow
            flow.future = asyncio.get_running_loop().create_future()
            log.info("MCP server %s needs authorization; waiting for the browser callback", server)

        async def callback() -> tuple[str, str | None]:
            while flow.future is None:          # redirect() has not run yet
                await asyncio.sleep(0.01)
            try:
                return await flow.future
            finally:
                self._drop(flow)

        return redirect, callback

    def authorization_url(self, server: str) -> str | None:
        flow = self._by_server.get(server)
        return flow.url if flow and not flow.consumed else None

    def server_for_state(self, state: str) -> str | None:
        flow = self._by_state.get(state)
        return flow.server if flow else None

    def complete(self, state: str, code: str) -> bool:
        flow = self._by_state.get(state)
        if flow is None or flow.future is None or flow.future.done():
            return False
        flow.consumed = True
        flow.future.set_result((code, state))
        return True

    def fail(self, state: str, error: str) -> bool:
        flow = self._by_state.get(state)
        if flow is None or flow.future is None or flow.future.done():
            return False
        flow.consumed = True
        flow.future.set_exception(RuntimeError(f"authorization failed: {error}"))
        return True

    def cancel(self, server: str) -> None:
        flow = self._by_server.get(server)
        if flow and flow.future and not flow.future.done():
            flow.future.set_exception(RuntimeError("authorization cancelled"))
        if flow:
            self._drop(flow)

    def _drop(self, flow: _Flow) -> None:
        if self._by_server.get(flow.server) is flow:
            self._by_server.pop(flow.server, None)
        if flow.state:
            self._by_state.pop(flow.state, None)


class StoredExpiryOAuthProvider(OAuthClientProvider):
    """`OAuthClientProvider` that remembers when stored tokens expire.

    The SDK loads stored tokens without their expiry, so after a restart an expired access token
    looks valid; the server answers 401, and the SDK answers a 401 with a full browser authorization
    rather than the refresh token it holds. Off the Settings page that is AuthorizationRequired, so
    Linear (24h access tokens) dropped to needs_auth every day with a working refresh token stored.
    Restoring the expiry lets the SDK's own check refresh before the token goes stale."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # One lock per server across providers: each connect builds a new provider, and two of them
        # refreshing the same rotating refresh token at once looks like token replay to Linear, which
        # revokes the whole grant. The second waits, then loads the first one's new tokens.
        self.context.lock = _server_lock(self.context.server_url)
        self._restored = False

    async def _initialize(self) -> None:
        await super()._initialize()
        if self._restored or self.context.current_tokens is None:
            # The SDK re-initializes after a failed refresh; restoring the expiry again would retry the
            # same dead refresh token on every request. Without it the stale token gets its 401.
            return
        self._restored = True
        storage = self.context.storage
        expiry = getattr(storage, "loaded_expiry", None)
        if expiry is not None:
            self.context.token_expiry_time = max(expiry - EXPIRY_MARGIN, 1.0)   # 0 would read as "no expiry"
        metadata = getattr(storage, "loaded_metadata", None)
        if metadata is not None and self.context.oauth_metadata is None:
            self.context.oauth_metadata = metadata       # so the refresh goes to the real token endpoint

    async def _remember_metadata(self) -> None:
        save = getattr(self.context.storage, "set_oauth_metadata", None)
        if save is not None and self.context.oauth_metadata is not None:
            await save(self.context.oauth_metadata)

    async def _handle_token_response(self, response) -> None:
        await super()._handle_token_response(response)
        await self._remember_metadata()

    async def _handle_refresh_response(self, response) -> bool:
        ok = await super()._handle_refresh_response(response)
        if ok:
            await self._remember_metadata()
        return ok


_LOCKS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, anyio.Lock]] = weakref.WeakKeyDictionary()


def _server_lock(server_url: str) -> anyio.Lock:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:            # built outside a loop (tests); nothing can race it there
        return anyio.Lock()
    return _LOCKS.setdefault(loop, {}).setdefault(server_url, anyio.Lock())


def build_oauth_provider(server_url: str, public_url: str, storage: DbTokenStorage, flows: PendingFlows,
                         server: str, allow: Callable[[], bool] | None = None, timeout: float = 300.0) -> OAuthClientProvider:
    redirect, callback = flows.handlers(server, allow=allow)
    metadata = OAuthClientMetadata(
        client_name="OpenBot",
        redirect_uris=[f"{public_url.rstrip('/')}{CALLBACK_PATH}"],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
    )
    return StoredExpiryOAuthProvider(server_url=server_url, client_metadata=metadata, storage=storage,
                               redirect_handler=redirect, callback_handler=callback, timeout=timeout)


__all__ = [
    "CALLBACK_PATH",
    "AuthorizationRequired",
    "DbTokenStorage",
    "PendingFlows",
    "StoredExpiryOAuthProvider",
    "build_oauth_provider",
    "load_or_create_key",
]
