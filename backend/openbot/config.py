import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Shared regex for validating Telegram Bot API tokens (format: <bot_id>:<token>).
TELEGRAM_TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]{30,}$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./.openbot/openbot.db"
    root_directory: Path | None = Field(default=None, validation_alias="OPENBOT_ROOT_DIRECTORY")
    openbot_api_key: str | None = None

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    openrouter_api_key: str | None = None
    xai_api_key: str | None = None
    # Local Ollama server, e.g. http://localhost:11434. No API key; setting this enables the provider.
    ollama_base_url: str | None = None
    ollama_model: str = "llama3.1"

    bot_model: str | None = None
    openrouter_model: str | None = None
    # Prefer these OpenRouter upstreams (CSV, e.g. `z-ai,fireworks`), falling back to others only when they cannot
    # serve a request. Each upstream has its own prompt cache; staying on one keeps it warm.
    openrouter_provider_order: Annotated[list[str], NoDecode] = []

    embedding_model: str = "openai:text-embedding-3-small"
    embedding_dims: int = 1536

    langsmith_tracing: bool = False
    langsmith_project: str = "openbot"

    workspace_root: Path = Path("./workspace")
    tools_dir: Path = Path("./tools")
    # MCP servers (docs/superpowers/specs/2026-09-17-mcp-design.md): Claude Code's mcpServers file; PUBLIC_URL builds
    # the OAuth redirect URI; credentials are Fernet-encrypted with MCP_TOKEN_KEY, or a key generated once into the file.
    mcp_config: Path = Path("./mcp.json")
    public_url: str = "http://127.0.0.1:8000"
    # The one key protecting every secret stored in the database (provider keys, MCP headers/env, OAuth
    # tokens): SECRET_KEY, or generated once into SECRET_KEY_FILE. MCP_TOKEN_KEY* are the older names.
    secret_key: str | None = None
    secret_key_file: Path = Path("./secret.key")
    mcp_token_key: str | None = None
    mcp_token_key_file: Path = Path("./mcp_token.key")

    max_concurrent_runs: int = 4
    max_bot_hops: int = 20
    # Token-efficiency controls. See README "Configuration".
    prompt_caching: bool = True          # add Anthropic cache breakpoints to every model call
    include_llm_call_details: bool = Field(default=True, validation_alias="OPENBOT_INCLUDE_LLM_CALL_DETAILS")  # expose per-call token details in activity events; launchers opt out explicitly
    direct_anthropic: bool = True        # send OpenRouter `anthropic/...` models to Anthropic directly when a key exists
    tool_output_cap: int = 8000          # max chars of any single tool result the model sees (head + tail kept)
    shell_output_cap: int = 4000         # tighter cap for run_shell, so dumping a file through cat/git show loses to read_file ranges
    context_trigger_tokens: int = 40000  # clear tool results from older turns once a run's messages exceed this
    context_clear_at_least: int = 10000  # ...and reclaim at least this many tokens per clearing, so clearings are rare
    summary_trigger_tokens: int = 60000  # summarize older history into one message once a run's messages exceed this
    summary_keep_messages: int = 24      # ...keeping this many recent messages verbatim (two turns of ~10 tool calls)
    max_model_calls_per_run: int = 60    # model turns per run before the agent is stopped (bots can lower it)
    history_token_budget: int = 24000
    history_max_messages: int = 80
    memory_reflection_delay: float = 30.0
    seed_demo_bots: bool = True
    # Model-call retries for transient upstream provider failures (see runtime/retry.py).
    model_retry_max_attempts: int = 3    # 0 or 1 turns retries off
    model_retry_base_delay: float = 2.0  # seconds before the first retry
    model_retry_backoff_cap: float = 60.0  # ceiling on any single retry delay

    # NoDecode: these are plain CSV strings in .env (e.g. `CORS_ORIGINS=http://a,http://b`), not
    # JSON, so pydantic-settings must not try to json.loads() the raw env value before our
    # `_split_csv` validator runs.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    frontend_dist: Path | None = Path("frontend/dist")
    log_level: str = "INFO"
    log_file: Path = Path("logs/openbot.log")
    # Days of per-thread/per-bot activity history kept in the database (see runtime/activity.py); 0 keeps everything.
    activity_log_retention_days: int = 14
    webhook_retry_delays: Annotated[list[float], NoDecode] = [5.0, 30.0, 120.0]

    # Telegram channel
    telegram_bot_token: str | None = None
    telegram_webhook_url: str | None = None
    telegram_webhook_secret: str | None = None
    telegram_transport: str = "long_polling"  # "long_polling" or "webhook"

    @model_validator(mode="after")
    def _apply_root_directory_defaults(self):
        """Use a caller-supplied root for defaults without overriding explicit settings."""
        if self.root_directory is None:
            return self
        root = Path(self.root_directory)
        if "workspace_root" not in self.model_fields_set:
            self.workspace_root = root
        if "database_url" not in self.model_fields_set:
            self.database_url = f"sqlite+aiosqlite:///{root / '.openbot' / 'openbot.db'}"
        return self

    @field_validator("cors_origins", "webhook_retry_delays", "openrouter_provider_order", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v

    @field_validator("bot_model", "openrouter_model", "ollama_base_url", mode="before")
    @classmethod
    def _empty_model_env_means_default(cls, v):
        if v == "":
            return None
        return v

    @field_validator("ollama_model", mode="before")
    @classmethod
    def _empty_ollama_model_means_default(cls, v):
        if v == "":
            return cls.model_fields["ollama_model"].default
        return v

    @field_validator("log_level", mode="before")
    @classmethod
    def _empty_log_level_means_default(cls, v):
        if v == "":
            return cls.model_fields["log_level"].default
        return v

    @field_validator("log_file", mode="before")
    @classmethod
    def _empty_log_file_means_default(cls, v):
        if v == "":
            return cls.model_fields["log_file"].default
        return v

    @field_validator("frontend_dist", mode="before")
    @classmethod
    def _empty_frontend_dist_means_default(cls, v):
        # An empty FRONTEND_DIST=  in .env must mean "use the default", not Path("") == Path(".")
        # (the repo root, which always exists and would otherwise get mounted as static files).
        if v == "":
            return cls.model_fields["frontend_dist"].default
        return v

    @field_validator("telegram_bot_token", mode="before")
    @classmethod
    def _validate_telegram_bot_token(cls, v):
        if v == "":
            return None
        if v is not None and not TELEGRAM_TOKEN_RE.match(str(v)):
            raise ValueError(
                "Invalid Telegram bot token format. Expected '{bot_id}:{token}' (e.g. 123456:ABC-DEF...)."
            )
        return v

    @field_validator("telegram_transport", mode="before")
    @classmethod
    def _validate_telegram_transport(cls, v):
        if isinstance(v, str):
            v = v.strip().lower()
        if v not in ("long_polling", "webhook"):
            raise ValueError("TELEGRAM_TRANSPORT must be 'long_polling' or 'webhook'.")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
