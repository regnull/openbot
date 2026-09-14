from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class RunContext:
    bot_id: str
    bot_handle: str
    bot_name: str
    thread_id: str
    run_id: str
    workspace_root: Path
    services: Any
