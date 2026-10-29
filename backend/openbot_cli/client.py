"""Thin HTTP/SSE client for the OpenBot REST API and the GitHub issues API.

Everything here is a thin wrapper around endpoints the server already exposes
under ``/api/v1``; there is no bespoke client->server protocol. The only
out-of-tree call is ``GET /repos/{owner}/{name}/issues`` against
``api.github.com``, because the server does not proxy GitHub issues.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
GITHUB_API_BASE = "https://api.github.com"

# Event names the server publishes over the /events SSE stream. Discovering these
# in the bus publish sites (runtime/delivery.py, runtime/runner.py, runtime/actors.py)
# keeps this client from inventing its own vocabulary.
EVENT_MESSAGE_CREATED = "message.created"
EVENT_RUN_UPDATED = "run.updated"
EVENT_RUN_EVENT = "run.event"
EVENT_WAITERS_UPDATED = "waiters.updated"
EVENT_BOTS_UPDATED = "bots.updated"


class OpenBotClientError(RuntimeError):
    """Raised when the server returns a non-2xx status."""


class OpenBotClient:
    """Minimal client for the OpenBot ``/api/v1`` REST surface."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
        *,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        if client is not None:
            self._client = client
            return
        headers = {"Accept": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key
        self._client = httpx.Client(
            base_url=self.base_url, headers=headers, timeout=timeout, follow_redirects=True
        )

    # -- low level ---------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = self._client.request(method, path, **kwargs)
        if resp.status_code >= 400:
            raise OpenBotClientError(
                f"{method} {path} -> {resp.status_code}: {resp.text[:300]}"
            )
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    # -- health / connect --------------------------------------------------

    def ping(self) -> dict[str, Any]:
        """Probe the server. The /health route is on the public (unauthenticated) router."""
        return self._request("GET", "/api/v1/health")

    # -- threads -----------------------------------------------------------

    def list_threads(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/v1/threads")

    def get_thread(self, thread_id: str, limit: int = 50) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/threads/{thread_id}", params={"limit": limit})

    def create_thread(
        self,
        title: str = "",
        handles: list[str] | None = None,
        default_bot: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"title": title, "handles": handles or []}
        if default_bot:
            body["default_bot_handle"] = default_bot
        return self._request("POST", "/api/v1/threads", json=body)

    def send_message(
        self,
        thread_id: str,
        content: str,
        to: list[str] | None = None,
        sender: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"content": content, "to": to or []}
        if sender:
            body["from"] = sender
        return self._request("POST", f"/api/v1/threads/{thread_id}/messages", json=body)

    # -- bots / runs -------------------------------------------------------

    def list_bots(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/v1/bots")

    def list_runs(self, thread_id: str | None = None) -> list[dict[str, Any]]:
        params = {"thread_id": thread_id} if thread_id else {}
        return self._request("GET", "/api/v1/runs", params=params)

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/runs/{run_id}")

    # -- SSE ---------------------------------------------------------------

    def stream_events(self, thread_id: str | None = None) -> Iterator[dict[str, Any]]:
        """Yield parsed SSE payloads from ``/api/v1/events`` until disconnected.

        Each yielded item is ``{"event": <name>, **data}``. Use a ``break`` from
        the caller to stop streaming.
        """
        headers = {"Accept": "text/event-stream"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        with self._client.stream(
            "GET",
            "/api/v1/events",
            params={"thread_id": thread_id} if thread_id else {},
            headers=headers,
            timeout=None,
        ) as resp:
            resp.raise_for_status()
            event = "message"
            for line in resp.iter_lines():
                if not line or line.startswith(":"):
                    continue  # comment / ping
                if line.startswith("event:"):
                    event = line[len("event:") :].strip()
                    continue
                if not line.startswith("data:"):
                    continue
                data_str = line[len("data:") :].strip()
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    data = {"raw": data_str}
                if isinstance(data, dict):
                    data.setdefault("event", event)
                yield data
                event = "message"

    # -- GitHub issues (no server endpoint exists) -------------------------

    def list_github_issues(
        self, repo: str = "regnull/openbot", *, state: str = "open", per_page: int = 30
    ) -> list[dict[str, Any]]:
        """Fetch issues directly from the GitHub REST API.

        The OpenBot server does not proxy GitHub, so this hits
        ``https://api.github.com/repos/{repo}/issues``. A token in
        ``GITHUB_TOKEN`` is optional and only raises the rate limit.
        """
        url = f"{GITHUB_API_BASE}/repos/{repo}/issues"
        headers = {"Accept": "application/vnd.github+json"}
        token = self._github_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        resp = httpx.get(
            url, params={"state": state, "per_page": per_page}, headers=headers, timeout=30.0
        )
        if resp.status_code >= 400:
            raise OpenBotClientError(f"github issues {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    @staticmethod
    def _github_token() -> str | None:
        import os

        return os.environ.get("GITHUB_TOKEN")


class GitHubIssuesClient:
    """Standalone client for GitHub issues, used when only ``issues`` is needed.

    Kept separate so the import surface of :class:`OpenBotClient` stays server-
    focused; the CLI wires the two together.
    """

    def __init__(self, token: str | None = None) -> None:
        self._token = token

    def list_issues(
        self, repo: str = "regnull/openbot", *, state: str = "open", per_page: int = 30
    ) -> list[dict[str, Any]]:
        url = f"{GITHUB_API_BASE}/repos/{repo}/issues"
        headers = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        resp = httpx.get(
            url, params={"state": state, "per_page": per_page}, headers=headers, timeout=30.0
        )
        if resp.status_code >= 400:
            raise OpenBotClientError(f"github issues {resp.status_code}: {resp.text[:300]}")
        return resp.json()
