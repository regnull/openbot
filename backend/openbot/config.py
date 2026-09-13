from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./openbot.db"
    openbot_api_key: str | None = None

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    openrouter_api_key: str | None = None
    xai_api_key: str | None = None

    embedding_model: str = "openai:text-embedding-3-small"
    embedding_dims: int = 1536

    langsmith_tracing: bool = False
    langsmith_project: str = "openbot"

    workspace_root: Path = Path("./workspace")
    tools_dir: Path = Path("./tools")

    max_concurrent_runs: int = 4
    max_bot_hops: int = 20
    history_token_budget: int = 24000
    history_max_messages: int = 80
    memory_reflection_delay: float = 30.0
    seed_demo_bots: bool = True

    cors_origins: list[str] = ["http://localhost:5173"]
    frontend_dist: Path | None = None
    webhook_retry_delays: list[float] = [5.0, 30.0, 120.0]

    @field_validator("cors_origins", "webhook_retry_delays", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
