from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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

    # NoDecode: these are plain CSV strings in .env (e.g. `CORS_ORIGINS=http://a,http://b`), not
    # JSON, so pydantic-settings must not try to json.loads() the raw env value before our
    # `_split_csv` validator runs.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    frontend_dist: Path | None = Path("frontend/dist")
    webhook_retry_delays: Annotated[list[float], NoDecode] = [5.0, 30.0, 120.0]

    @field_validator("cors_origins", "webhook_retry_delays", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v

    @field_validator("frontend_dist", mode="before")
    @classmethod
    def _empty_frontend_dist_means_default(cls, v):
        # An empty FRONTEND_DIST=  in .env must mean "use the default", not Path("") == Path(".")
        # (the repo root, which always exists and would otherwise get mounted as static files).
        if v == "":
            return cls.model_fields["frontend_dist"].default
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
