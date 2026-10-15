import logging
from pathlib import Path

from langchain.tools import tool

from openbot.tools.registry import ToolRegistry


def test_register_and_resolve():
    @tool
    def hello(name: str) -> str:
        """Say hello."""
        return f"hi {name}"
    reg = ToolRegistry()
    reg.register(hello)
    assert reg.has("hello") and reg.get("hello") is hello
    assert reg.resolve(["hello"]) == [hello]


def test_resolve_warns_and_drops_unknown(caplog):
    """A DB tool list can be newer than the registry snapshotted at server start."""
    @tool
    def hello(name: str) -> str:
        """Say hello."""
        return f"hi {name}"
    reg = ToolRegistry()
    reg.register(hello)
    with caplog.at_level(logging.WARNING, logger="openbot.tools.registry"):
        assert reg.resolve(["hello", "brand_new_tool"]) == [hello]
    assert "brand_new_tool" in caplog.text and "restart" in caplog.text


def test_load_plugins(tmp_path: Path):
    (tmp_path / "good.py").write_text(
        'from langchain.tools import tool\n\n@tool\ndef add(a: int, b: int) -> int:\n    """Add."""\n    return a + b\n')
    (tmp_path / "bad.py").write_text("raise RuntimeError('boom')\n")
    reg = ToolRegistry()
    reg.load_plugins(tmp_path)
    assert reg.has("add")
    assert reg.get("add").invoke({"a": 1, "b": 2}) == 3
    assert reg.specs()[0].source.endswith("good.py")
    assert len(reg.load_errors) == 1 and "boom" in reg.load_errors[0]["error"]


def test_missing_dir_is_fine(tmp_path: Path):
    reg = ToolRegistry()
    reg.load_plugins(tmp_path / "missing")
    assert reg.specs() == [] and reg.load_errors == []


async def test_tools_endpoint(client):
    r = await client.get("/api/v1/tools")
    assert r.status_code == 200
    names = {t["name"] for t in r.json()["tools"]}
    assert {"run_shell", "read_file", "write_file", "list_files", "http_request", "fetch_url"} <= names
