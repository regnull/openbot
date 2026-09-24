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
RULES = (
    (re.compile(r"(?:from|require\s*\()\s*[\"']node:"), "Node built-in imports"),
    (re.compile(r"(?:from|require\s*\()\s*[\"'](?:fs|path|child_process|net|tls|sqlite3|better-sqlite3)"), "server/runtime imports"),
    (re.compile(r"\b(?:indexedDB|IDBDatabase)\b"), "client-side persistence"),
    (re.compile(r"\b(?:XMLHttpRequest|WebSocket)\b"), "direct integration transport (use the API client/SSE layer)"),
)


def main() -> int:
    violations: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if path.suffix not in {".ts", ".tsx", ".js", ".jsx"} or path.name.endswith(".test.ts") or path.name.endswith(".test.tsx"):
            continue
        text = path.read_text(encoding="utf-8")
        for pattern, description in RULES:
            for line_number, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    violations.append(f"{path.relative_to(ROOT)}:{line_number}: {description}: {line.strip()}")
    if violations:
        print("Client boundary violations found:")
        print("\n".join(violations))
        return 1
    print("Client boundary check passed: frontend/src contains no backend-owned runtime or persistence access.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
