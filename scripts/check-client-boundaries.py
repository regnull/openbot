#!/usr/bin/env python3
"""Reject backend responsibilities from the browser renderer.

The Electron main process is an application shell (process/window lifecycle), so this
check intentionally scopes itself to frontend/src: the shared browser renderer must
remain an API client and presentation layer for every supported entry point. Tests may
use Node helpers to load fixtures and are excluded from the production check.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "frontend" / "src"
TRANSPORT_MODULES = {"api/client.ts", "api/sse.ts"}
NODE_MODULES = (
    "assert|buffer|child_process|cluster|crypto|dgram|dns|fs|http|https|module|net|os|path|"
    "perf_hooks|process|readline|stream|tls|url|util|v8|vm|worker_threads|zlib|"
    "sqlite3|better-sqlite3"
)
MODULE_SPECIFIER = rf'''["']\s*(?:node:)?(?:{NODE_MODULES})\s*["']'''
RULES = (
    (
        re.compile(
            rf"(?:\bfrom\s*|\bimport\s*\(\s*|\brequire(?:\.resolve)?\s*\(\s*|"
            rf"\bimport\s+(?:(?:[^;\"'\\n]+?)\s+from\s+)?){MODULE_SPECIFIER}"
        ),
        "Node/server runtime imports",
    ),
    (re.compile(r"\b(?:indexedDB|IDBDatabase)\b"), "client-side persistence"),
)
TRANSPORT_RULES = (
    (
        re.compile(r"\b(?:(?:window|globalThis|global)\s*\.\s*)?fetch\s*\("),
        "direct HTTP transport (use the API client)",
    ),
    (
        re.compile(
            r"\b(?:(?:window|globalThis|global)\s*\.\s*)?"
            r"(?:XMLHttpRequest|WebSocket|EventSource)\s*\("
        ),
        "direct integration transport (use the API/SSE layer)",
    ),
)


def violations_for_text(text: str, relative_path: str) -> list[str]:
    """Return boundary violations for one source file.

    REST and SSE transport are deliberately allowlisted to their two adapter modules;
    all other renderer files must consume those adapters rather than open connections.
    """
    violations: list[str] = []
    lines = text.splitlines()
    for pattern, description in RULES:
        for line_number, line in enumerate(lines, 1):
            if pattern.search(line):
                violations.append(f"{relative_path}:{line_number}: {description}: {line.strip()}")
    if relative_path not in TRANSPORT_MODULES:
        for pattern, description in TRANSPORT_RULES:
            for line_number, line in enumerate(lines, 1):
                if pattern.search(line):
                    violations.append(f"{relative_path}:{line_number}: {description}: {line.strip()}")
    return violations


def main() -> int:
    violations: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if path.suffix not in {".ts", ".tsx", ".js", ".jsx"} or path.name.endswith(
            (".test.ts", ".test.tsx", ".test.js", ".test.jsx")
        ):
            continue
        violations.extend(violations_for_text(path.read_text(encoding="utf-8"), str(path.relative_to(ROOT))))
    if violations:
        print("Client boundary violations found:")
        print("\n".join(violations))
        return 1
    print("Client boundary check passed: frontend/src contains no backend-owned runtime or persistence access.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
