from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from openbot.config import Settings


@dataclass
class Services:
    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]
    registry: Any = None       # ToolRegistry
    bus: Any = None            # EventBus
    store: Any = None          # langgraph BaseStore
    checkpointer: Any = None   # langgraph BaseCheckpointSaver
    actors: Any = None         # ActorSystem
    runner: Any = None         # Runner
    reflector: Any = None      # MemoryReflector
    model_factory: Callable[[Any], Any] | None = None  # (Actor) -> BaseChatModel
    http_client: Any = None    # httpx.AsyncClient for webhook delivery
    mcp: Any = None            # McpManager
    secrets: Any = None        # runtime.secrets.SecretBox for secrets stored in the database
    langgraph_stack: Any = None  # AsyncExitStack holding the checkpointer/store; replaced when embeddings change
    env_defaults: dict = field(default_factory=dict)  # tunables' values before stored overrides (see runtime/app_settings.py)
    _owned_resources: list = field(default_factory=list)
    _telegram_listener: Any = None  # TelegramDeliveryListener (started in start_background)
    _seed_lock: asyncio.Lock = field(default_factory=asyncio.Lock)