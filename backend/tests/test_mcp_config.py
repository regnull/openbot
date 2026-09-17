"""mcp.json parsing: Claude Code's mcpServers shape, ${VAR} expansion, transport detection."""
import json

import pytest

from openbot.mcp.config import McpConfigError, load_mcp_config


def _write(tmp_path, data):
    p = tmp_path / "mcp.json"
    p.write_text(json.dumps(data))
    return p


def test_missing_file_means_no_servers(tmp_path):
    assert load_mcp_config(tmp_path / "nope.json", env={}) == []


def test_stdio_and_http_servers_with_env_expansion(tmp_path, monkeypatch):
    p = _write(tmp_path, {"mcpServers": {
        "github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"], "env": {"GITHUB_TOKEN": "${GH}"}, "cwd": "/tmp"},
        "linear": {"url": "https://mcp.linear.app/mcp"},
        "internal": {"url": "https://mcp.${HOST}/mcp", "headers": {"Authorization": "Bearer ${KEY}"}},
        "off": {"url": "https://x/mcp", "enabled": False},
    }})
    servers = {s.name: s for s in load_mcp_config(p, env={"GH": "ghp_1", "HOST": "example.com", "KEY": "k1"})}
    gh = servers["github"]
    assert gh.transport == "stdio" and gh.command == "npx" and gh.args[1] == "@modelcontextprotocol/server-github"
    assert gh.env == {"GITHUB_TOKEN": "ghp_1"} and gh.cwd == "/tmp" and gh.oauth is False
    lin = servers["linear"]
    assert lin.transport == "http" and lin.url == "https://mcp.linear.app/mcp" and lin.oauth is True    # no static auth header
    internal = servers["internal"]
    assert internal.url == "https://mcp.example.com/mcp" and internal.headers == {"Authorization": "Bearer k1"} and internal.oauth is False
    assert servers["off"].enabled is False


def test_unset_variable_is_an_error_for_that_server_only(tmp_path):
    p = _write(tmp_path, {"mcpServers": {
        "ok": {"url": "https://a/mcp"},
        "bad": {"command": "x", "env": {"T": "${MISSING}"}},
    }})
    servers = {s.name: s for s in load_mcp_config(p, env={})}
    assert servers["ok"].error is None
    assert servers["bad"].error and "MISSING" in servers["bad"].error


def test_malformed_config_raises(tmp_path):
    p = tmp_path / "mcp.json"
    p.write_text("{not json")
    with pytest.raises(McpConfigError):
        load_mcp_config(p, env={})
    p.write_text(json.dumps({"mcpServers": {"x": {"args": ["a"]}}}))         # neither command nor url
    with pytest.raises(McpConfigError):
        load_mcp_config(p, env={})
    p.write_text(json.dumps({"mcpServers": {"bad name!": {"url": "https://a"}}}))
    with pytest.raises(McpConfigError):
        load_mcp_config(p, env={})
