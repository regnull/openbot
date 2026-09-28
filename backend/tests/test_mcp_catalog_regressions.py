"""Offline metadata/config/API regressions, not third-party server health tests."""
from unittest.mock import AsyncMock

import pytest

from openbot.mcp.catalog import CATALOG, CATALOG_BY_ID
from openbot.mcp.config import build_server, validate_spec

BASELINE_IDS = {
    "filesystem", "git", "memory", "sequential-thinking", "time", "fetch", "github", "gitlab",
    "postgres", "sqlite", "puppeteer", "brave-search", "slack", "google-drive", "everart",
    "serena", "context7", "delimit", "playwright", "notion", "linear", "sentry", "stripe",
    "supabase", "vercel", "aws", "cloudflare", "mongodb", "redis", "duckdb", "docker",
    "tavily", "firecrawl", "exa", "perplexity",
}
QUARANTINED = {
    "github", "gitlab", "postgres", "sqlite", "puppeteer", "brave-search", "slack",
    "google-drive", "everart", "mongodb", "redis", "notion", "duckdb", "vercel",
    "stripe", "cloudflare",
}


def test_complete_baseline_and_dispositions():
    assert set(CATALOG_BY_ID) == BASELINE_IDS
    assert len(CATALOG) == len(BASELINE_IDS)
    assert {e["id"] for e in CATALOG if e["status"] != "template"} == QUARANTINED
    for entry in CATALOG:
        assert entry["status"] in ("template", "deprecated", "unverified")
        assert entry["status_reason"]
    assert "positional database URL" in " ".join(CATALOG_BY_ID["postgres"]["compatibility"])
    assert not CATALOG_BY_ID["postgres"]["required_credentials"]
    assert "servers-archived" in CATALOG_BY_ID["sqlite"]["source_url"]
    assert "mongodb-mcp-server" in CATALOG_BY_ID["mongodb"]["status_reason"]


@pytest.mark.parametrize("ident", ["git", "time", "fetch", "docker"])
def test_correct_python_identity(ident):
    entry = CATALOG_BY_ID[ident]
    assert entry["command"] == "uvx"
    assert entry["args"][0] == f"mcp-server-{ident}"


def test_launch_details_and_provenance():
    assert CATALOG_BY_ID["perplexity"]["args"] == ["-y", "@perplexity-ai/mcp-server"]
    assert CATALOG_BY_ID["perplexity"]["source_url"] == "https://github.com/perplexityai/modelcontextprotocol"
    assert CATALOG_BY_ID["docker"]["source_url"] == "https://github.com/ckreiling/mcp-server-docker"
    assert CATALOG_BY_ID["sqlite"]["command"] == "uvx"
    assert CATALOG_BY_ID["sqlite"]["args"] == [
        "--with", "mcp<2", "mcp-server-sqlite", "--db-path", "${OPENBOT_MCP_SQLITE_DB}"
    ]
    assert CATALOG_BY_ID["delimit"]["args"] == ["-y", "delimit-cli", "mcp"]
    for ident in ("duckdb", "vercel"):
        assert CATALOG_BY_ID[ident]["status"] == "unverified"
        assert CATALOG_BY_ID[ident]["command"] == "" and CATALOG_BY_ID[ident]["args"] == []


def test_auth_and_service_scope_are_not_misrepresented():
    assert "OAuth" in " ".join(CATALOG_BY_ID["linear"]["required_credentials"])
    assert not CATALOG_BY_ID["context7"]["required_credentials"]
    assert "optional" in " ".join(CATALOG_BY_ID["context7"]["compatibility"])
    assert CATALOG_BY_ID["sentry"]["required_credentials"] == ["SENTRY_ACCESS_TOKEN"]
    assert CATALOG_BY_ID["aws"]["name"] == "AWS Documentation"
    assert "public" in CATALOG_BY_ID["aws"]["description"]


def test_filesystem_template_fails_closed_until_explicit_path(tmp_path):
    entry = CATALOG_BY_ID["filesystem"]
    spec = validate_spec("fs", {"command": entry["command"], "args": entry["args"], "enabled": False})
    missing = build_server("fs", spec, env={})
    assert missing.error == "environment variable OPENBOT_MCP_ALLOWED_DIR is not set"
    assert not missing.enabled
    # Server Env is not the process environment used to expand Args.
    assert build_server("fs", {**spec, "env": {"OPENBOT_MCP_ALLOWED_DIR": str(tmp_path)}}, env={}).error
    configured = build_server("fs", spec, env={"OPENBOT_MCP_ALLOWED_DIR": str(tmp_path)})
    assert configured.error is None and configured.args[-1] == str(tmp_path)
    assert not configured.enabled


async def test_api_exposes_all_dispositions_without_connection(client, services, monkeypatch):
    connect = AsyncMock(side_effect=AssertionError("catalog must not connect"))
    monkeypatch.setattr(services.mcp, "connect", connect)
    response = await client.get("/api/v1/mcp/catalog")
    assert response.status_code == 200
    entries = response.json()
    assert {e["id"] for e in entries} == BASELINE_IDS
    assert {e["id"] for e in entries if e["status"] != "template"} == QUARANTINED
    assert all(e["status_reason"] for e in entries)
    connect.assert_not_called()


@pytest.mark.parametrize("entry", CATALOG, ids=lambda e: e["id"])
async def test_every_catalog_disposition_is_enforced(client, services, monkeypatch, entry):
    connect = AsyncMock(side_effect=AssertionError("catalog install must not connect"))
    monkeypatch.setattr(services.mcp, "connect", connect)
    name = f"catalog-{entry['id']}"
    response = await client.post(f"/api/v1/mcp/catalog/{entry['id']}/install",
                                json={"name": name, "enabled": True})
    if entry["id"] in QUARANTINED:
        assert response.status_code == 422
        assert response.json()["detail"] == entry["status_reason"]
        assert await services.mcp.store.raw(name) is None
        assert not services.mcp.has(name)
    else:
        assert response.status_code == 201, response.text
        assert response.json()["enabled"] is False
        assert response.json()["tools"] == []
        spec = await services.mcp.store.raw(name)
        assert spec["enabled"] is False
        if entry["url"]:
            assert spec["url"] == entry["url"]
        else:
            assert spec["command"] == entry["command"] and spec["args"] == entry["args"]
    connect.assert_not_called()


async def test_existing_install_is_not_migrated(client, services):
    old = {"name": "time", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-time"], "enabled": False}
    assert (await client.post("/api/v1/mcp/servers", json=old)).status_code == 201
    before = await services.mcp.store.raw("time")
    await client.get("/api/v1/mcp/catalog")
    assert (await client.post("/api/v1/mcp/catalog/time/install", json={"name": "time"})).status_code == 409
    assert await services.mcp.store.raw("time") == before
    edited = await client.patch("/api/v1/mcp/servers/time", json={"command": "uvx", "args": ["mcp-server-time"], "enabled": False})
    assert edited.status_code == 200 and edited.json()["enabled"] is False
    assert edited.json()["command"] == "uvx"
