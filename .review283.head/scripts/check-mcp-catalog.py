"""Opt-in metadata-only registry audit. Never downloads archives or runs an MCP server.

Default invocation is offline; pass --online to issue public registry GETs. JSON output
keeps registry identity, provenance hints, catalog disposition, and runtime evidence separate.
A metadata-only result is NOT a working-server or artifact-authenticity claim.
"""
from __future__ import annotations

import argparse
import json
import re
import runpy
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def package_identity(entry: dict) -> tuple[str, str] | None:
    if entry["transport"] == "http" or not entry["command"]:
        return None
    args = entry["args"]
    if entry["command"] == "npx" and len(args) >= 2 and args[0] == "-y":
        # Strip an optional version/tag, preserving the @scope/name prefix.
        return "npm", re.sub(r"(?<=.)@[^/]+$", "", args[1])
    if entry["command"] == "uvx" and args:
        args = list(args)
        while len(args) >= 2 and args[0] == "--with":
            if not args[1] or args[1].startswith("-"):
                raise ValueError("invalid uvx dependency constraint")
            args = args[2:]
        if not args:
            raise ValueError("missing uvx package")
        package = args[1] if args[0] == "--from" and len(args) >= 3 else args[0]
        if package.startswith("-"):
            raise ValueError("unrecognised uvx package syntax")
        return "pypi", package.split("@", 1)[0]
    raise ValueError("unrecognised catalog runner")


def github_repo(url: str) -> str | None:
    parsed = urllib.parse.urlsplit(url.removeprefix("git+"))
    if parsed.hostname != "github.com":
        return None
    parts = parsed.path.strip("/").split("/")
    return "/".join(parts[:2]).removesuffix(".git").lower() if len(parts) >= 2 else None


def assess_metadata(entry: dict, registry: str, package: str, data: dict) -> dict:
    info = data.get("info", {}) if registry == "pypi" else data
    def normalize(s: str) -> str:
        return re.sub(r"[-_.]+", "-", s).lower() if registry == "pypi" else s
    result = {"name": info.get("name"), "version": info.get("version"),
              "deprecated": info.get("deprecated"),
              "runtime_requirements": info.get("requires_python") if registry == "pypi" else info.get("engines"),
              "bin": info.get("bin") if registry == "npm" else None,
              "entry_point": "not verified from distribution" if registry == "pypi" else "registry declaration only"}
    if normalize(str(info.get("name", ""))) != normalize(package) or not info.get("version"):
        return {**result, "status": "invalid-metadata", "reason": "name mismatch or missing version"}
    if registry == "npm":
        repository = info.get("repository") or ""
        urls = [repository.get("url", "") if isinstance(repository, dict) else repository]
        binary = info.get("bin")
        if not (isinstance(binary, str) and binary or isinstance(binary, dict) and binary and
                all(isinstance(path, str) and path for path in binary.values())):
            return {**result, "status": "invalid-metadata", "reason": "no executable declared by npm package"}
    else:
        urls = list((info.get("project_urls") or {}).values())
    repos = sorted({repo for url in urls if isinstance(url, str) and (repo := github_repo(url))})
    expected = github_repo(entry["source_url"])
    result.update(declared_repositories=repos, expected_repository=expected,
                  source_alignment="matching declaration" if expected in repos else "needs review")
    if info.get("deprecated"):
        return {**result, "status": "deprecated", "reason": str(info["deprecated"])}
    if expected not in repos:
        return {**result, "status": "needs-source-review", "reason": "repository absent or differs; redirects/archives require manual upstream review"}
    return {**result, "status": "metadata-only", "reason": "registry declarations align; artifact, launch, initialize and tools remain untested"}


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "OpenBot-catalog-metadata-check"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def check_entry(entry: dict, online: bool, fetch=fetch_json) -> dict:
    result = {"id": entry["id"], "catalog_status": entry["status"],
              "initialize": "not-run", "tools_list": "not-run", "tool_calls": "not-run"}
    try:
        identity = package_identity(entry)
    except ValueError as exc:
        return {**result, "status": "invalid-config", "reason": str(exc)}
    if identity is None:
        return {**result, "status": "not-applicable" if entry["transport"] == "http" else "identity-unresolved",
                "reason": "remote endpoint not contacted" if entry["transport"] == "http" else entry["status_reason"]}
    registry, package = identity
    encoded = urllib.parse.quote(package, safe="")
    url = f"https://registry.npmjs.org/{encoded}/latest" if registry == "npm" else f"https://pypi.org/pypi/{encoded}/json"
    result.update(registry=registry, package=package, metadata_url=url)
    if not online:
        return {**result, "status": "not-checked", "reason": "pass --online for metadata GETs only"}
    try:
        data = fetch(url)
        if not isinstance(data, dict):
            raise TypeError("registry JSON must be an object")
        return {**result, **assess_metadata(entry, registry, package, data)}
    except urllib.error.HTTPError as exc:
        return {**result, "status": "not-found" if exc.code == 404 else "registry-error", "http_status": exc.code, "reason": str(exc)}
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return {**result, "status": "registry-error", "reason": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--online", action="store_true", help="public metadata GETs only; no package installation/execution")
    parser.add_argument("--ids", nargs="+", help="check only these catalog IDs")
    options = parser.parse_args()
    catalog = runpy.run_path(str(ROOT / "backend/openbot/mcp/catalog.py"))["CATALOG"]
    if options.ids and set(options.ids) - {e["id"] for e in catalog}:
        parser.error("unknown catalog ID")
    entries = [e for e in catalog if not options.ids or e["id"] in options.ids]
    results = [check_entry(e, options.online) for e in entries]
    print(json.dumps({"checked_at": datetime.now(timezone.utc).isoformat(), "online": options.online,
                      "scope": "metadata only; no server health certification", "entries": results}, indent=2))
    return int(any(e["status"] in {"invalid-config", "invalid-metadata", "not-found", "registry-error"} for e in results))


if __name__ == "__main__":
    raise SystemExit(main())
