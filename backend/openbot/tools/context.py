from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class RunContext:
    actor_id: str
    actor_handle: str
    actor_name: str
    thread_id: str
    run_id: str
    workspace_root: Path
    services: Any
    working_directory: str | None = None
    hop: int = 0
    tool_output_cap: int = 8000
