"""Persistent connection config for the OpenBot terminal client.

Stored as a tiny JSON file in the user's config dir so ``openbot connect`` only
needs to run once per machine. The schema is intentionally flat and forward
compatible — unknown keys are preserved on write.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "openbot-cli"
CONFIG_PATH = CONFIG_DIR / "config.json"


class ConfigError(RuntimeError):
    pass


def load_config(path: Path | None = None) -> dict[str, Any]:
    path = path or CONFIG_PATH
    if not path.exists():
        return {"base_url": DEFAULT_BASE_URL, "api_key": None}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:  # pragma: no cover - defensive
        raise ConfigError(f"could not read config {path}: {e}") from e
    data.setdefault("base_url", DEFAULT_BASE_URL)
    return data


def save_config(data: dict[str, Any], path: Path | None = None) -> Path:
    path = path or CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    return path


def resolve(base_url: str | None, api_key: str | None, path: Path | None = None) -> tuple[str, str | None]:
    """Merge explicit flags over stored config; returns (base_url, api_key)."""
    cfg = load_config(path)
    return (base_url or cfg["base_url"]), (api_key or cfg.get("api_key"))
