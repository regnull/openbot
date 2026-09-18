async def test_list_directories(client, services):
    root = services.settings.workspace_root
    (root / "alpha" / "inner").mkdir(parents=True)
    (root / "beta").mkdir()
    (root / ".hidden").mkdir()
    (root / "notes.txt").write_text("x")

    r = await client.get("/api/v1/workspace/directories")
    assert r.status_code == 200, r.text
    assert r.json() == {"path": ".", "parent": None,
                        "entries": [{"name": "alpha", "path": "alpha"}, {"name": "beta", "path": "beta"}]}

    r = await client.get("/api/v1/workspace/directories", params={"path": "alpha"})
    assert r.json() == {"path": "alpha", "parent": ".", "entries": [{"name": "inner", "path": "alpha/inner"}]}

    r = await client.get("/api/v1/workspace/directories", params={"path": "~"})
    assert r.status_code == 200 and r.json()["path"] == "~" and r.json()["parent"] is None

    for bad in ("../x", "/etc", "missing", "notes.txt"):
        r = await client.get("/api/v1/workspace/directories", params={"path": bad})
        assert r.status_code == 422, (bad, r.text)
