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
