from openbot.mcp.catalog import CATALOG, CATALOG_BY_ID


def test_catalog_is_curated_and_complete():
    assert len(CATALOG) >= 30
    assert len(CATALOG_BY_ID) == len(CATALOG)
    for entry in CATALOG:
        assert entry["id"] and entry["name"] and entry["description"]
        assert entry["provider"] and entry["source_url"].startswith("https://")
        assert entry["command"] and entry["args"]
        assert entry["transport"] == "stdio"


def test_catalog_contains_requested_examples():
    assert {"serena", "context7"} <= CATALOG_BY_ID.keys()


async def test_catalog_install_is_disabled_and_rejects_unknown_or_duplicate(settings, tmp_path):
    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient
    from openbot.main import create_app
    from tests.conftest import build_test_services

    settings.mcp_config = tmp_path / "mcp.json"
    settings.mcp_config.write_text('{"mcpServers": {}}')
    settings.mcp_token_key_file = tmp_path / "key"
    services = await build_test_services(settings)
    app = create_app(settings, services=services)
    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        entries = (await client.get("/api/v1/mcp/catalog")).json()
        assert len(entries) >= 30
        response = await client.post("/api/v1/mcp/catalog/time/install", json={"name": "catalog-time"})
        assert response.status_code == 201, response.text
        installed = response.json()
        assert installed["enabled"] is False
        assert installed["command"] == "npx"
        assert (await client.post("/api/v1/mcp/catalog/time/install", json={"name": "catalog-time"})).status_code == 409
        assert (await client.post("/api/v1/mcp/catalog/no-such/install", json={"name": "nope"})).status_code == 404
