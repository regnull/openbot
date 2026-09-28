"""Offline tests for the opt-in metadata checker: fixtures are not runtime receipts."""
import runpy
import urllib.error
from copy import deepcopy
from email.message import Message
from pathlib import Path
from unittest.mock import Mock

import pytest

from openbot.mcp.catalog import CATALOG, CATALOG_BY_ID

CHECKER = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/check-mcp-catalog.py"))
identity = CHECKER["package_identity"]
assess = CHECKER["assess_metadata"]
check = CHECKER["check_entry"]


def test_special_package_extraction():
    assert identity(CATALOG_BY_ID["sqlite"]) == ("pypi", "mcp-server-sqlite")
    assert identity(CATALOG_BY_ID["serena"]) == ("pypi", "serena-agent")
    assert identity(CATALOG_BY_ID["aws"]) == ("pypi", "awslabs.aws-documentation-mcp-server")
    assert identity(CATALOG_BY_ID["delimit"]) == ("npm", "delimit-cli")
    assert identity(CATALOG_BY_ID["perplexity"]) == ("npm", "@perplexity-ai/mcp-server")
    assert identity(CATALOG_BY_ID["linear"]) is None
    assert identity(CATALOG_BY_ID["duckdb"]) is None
    assert identity({**CATALOG_BY_ID["perplexity"], "args": ["-y", "@perplexity-ai/mcp-server@1.3.0"]}) == ("npm", "@perplexity-ai/mcp-server")


@pytest.mark.parametrize("args", [["--with"], ["--with", "mcp<2"], ["--with", "--bad", "pkg"], ["--from"]])
def test_malformed_uvx_options_fail_closed(args):
    with pytest.raises(ValueError):
        identity({**CATALOG_BY_ID["sqlite"], "args": args})


def test_offline_does_not_fetch_or_infer_health():
    fetch = Mock(side_effect=AssertionError("offline check must not fetch"))
    results = [check(e, False, fetch=fetch) for e in CATALOG]
    fetch.assert_not_called()
    assert len(results) == 35
    assert all(r["initialize"] == r["tools_list"] == r["tool_calls"] == "not-run" for r in results)


def test_remote_and_unresolved_do_not_contact_endpoints_even_online():
    fetch = Mock(side_effect=AssertionError("no server endpoint requests"))
    for ident in ("linear", "duckdb", "vercel"):
        assert check(CATALOG_BY_ID[ident], True, fetch=fetch)["status"] in ("identity-unresolved", "not-applicable")
    fetch.assert_not_called()


# Synthetic registry records exercise classification; they are deliberately not upstream receipts.
NPM = {"name": "mcp-server-docker", "version": "1.0.0", "bin": {"mcp-server-docker": "index.js"},
       "repository": {"url": "git+https://github.com/adamdude828/mcp-server-docker.git"}}


def test_resolving_namesake_is_not_source_alignment():
    result = assess(CATALOG_BY_ID["docker"], "npm", "mcp-server-docker", NPM)
    assert result["status"] == "needs-source-review"
    assert result["source_alignment"] == "needs review"


@pytest.mark.parametrize("url", [
    "https://notgithub.com/ckreiling/mcp-server-docker",
    "https://example.com/github.com/ckreiling/mcp-server-docker",
    "https://github.com.example.com/ckreiling/mcp-server-docker",
])
def test_repository_hint_requires_exact_host(url):
    data = {**NPM, "repository": {"url": url}}
    assert assess(CATALOG_BY_ID["docker"], "npm", "mcp-server-docker", data)["status"] == "needs-source-review"


@pytest.mark.parametrize("change, expected", [
    ({"name": "wrong-name"}, "invalid-metadata"),
    ({"version": ""}, "invalid-metadata"),
    ({"bin": {}}, "invalid-metadata"),
    ({"bin": {"cli": None}}, "invalid-metadata"),
    ({"deprecated": "unsupported"}, "deprecated"),
    ({"repository": {}}, "needs-source-review"),
])
def test_metadata_errors_and_deprecation_are_distinct(change, expected):
    data = {**deepcopy(NPM), **change}
    assert assess(CATALOG_BY_ID["docker"], "npm", "mcp-server-docker", data)["status"] == expected


def test_matching_python_metadata_still_has_no_verified_console_script():
    data = {"info": {"name": "mcp_server_docker", "version": "0.3.0", "requires_python": ">=3.12",
                     "project_urls": {"Repository": "https://github.com/ckreiling/mcp-server-docker"}}}
    result = assess(CATALOG_BY_ID["docker"], "pypi", "mcp-server-docker", data)
    assert result["status"] == "metadata-only"
    assert result["entry_point"] == "not verified from distribution"
    assert result["runtime_requirements"] == ">=3.12"


@pytest.mark.parametrize("code, expected", [(404, "not-found"), (429, "registry-error"), (503, "registry-error")])
def test_registry_http_errors(code, expected):
    fetch = Mock(side_effect=urllib.error.HTTPError("https://example.invalid", code, "test", Message(), None))
    result = check(CATALOG_BY_ID["time"], True, fetch=fetch)
    assert result["status"] == expected and result["http_status"] == code
    assert result["initialize"] == "not-run"


@pytest.mark.parametrize("error", [TimeoutError("timeout"), ValueError("invalid JSON")])
def test_registry_transport_and_parse_errors(error):
    result = check(CATALOG_BY_ID["time"], True, fetch=Mock(side_effect=error))
    assert result["status"] == "registry-error"


def test_invalid_registry_shape():
    assert check(CATALOG_BY_ID["time"], True, fetch=lambda _: ["not an object"])["status"] == "registry-error"
