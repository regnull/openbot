"""Regression tests for the FRONTEND_DIST default-fallback and CSV env-var parsing fixes.

Both bugs were invisible to the rest of the suite because conftest.py's `settings` fixture builds
`Settings` from Python literals directly (bypassing env-var parsing) and passes `_env_file=None`.
These tests instead go through the real env-var / .env parsing path pydantic-settings uses at
startup, which is exactly where both bugs surfaced.
"""
from pathlib import Path

from openbot.config import Settings


def test_empty_frontend_dist_env_uses_default_not_repo_root(monkeypatch):
    # Path("") normalizes to Path(".") -- the repo root, which always exists -- so without the
    # fallback validator this would make main.py mount the entire repo as static files.
    monkeypatch.setenv("FRONTEND_DIST", "")
    settings = Settings(_env_file=None)
    assert settings.frontend_dist == Path("frontend/dist")
    assert settings.frontend_dist != Path(".")


def test_unset_frontend_dist_also_uses_default(monkeypatch):
    monkeypatch.delenv("FRONTEND_DIST", raising=False)
    settings = Settings(_env_file=None)
    assert settings.frontend_dist == Path("frontend/dist")



def test_database_url_defaults_to_openbot_directory(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    settings = Settings(_env_file=None)
    assert settings.database_url == "sqlite+aiosqlite:///./.openbot/openbot.db"


def test_database_url_override_is_preserved(monkeypatch):
    override = "sqlite+aiosqlite:////tmp/custom-openbot.db"
    monkeypatch.setenv("DATABASE_URL", override)
    settings = Settings(_env_file=None)
    assert settings.database_url == override



def test_sqlite_parent_is_created_for_default_and_override(tmp_path):
    from openbot.db.session import ensure_sqlite_parent

    default_path = tmp_path / ".openbot" / "openbot.db"
    override_path = tmp_path / "custom" / "openbot.db"
    ensure_sqlite_parent(f"sqlite+aiosqlite:///{default_path}")
    ensure_sqlite_parent(f"sqlite+aiosqlite:///{override_path}")
    assert default_path.parent.is_dir()
    assert override_path.parent.is_dir()


def test_empty_bot_model_env_uses_default_marker(monkeypatch):
    monkeypatch.setenv("BOT_MODEL", "")
    monkeypatch.setenv("OPENROUTER_MODEL", "")
    settings = Settings(_env_file=None)
    assert settings.bot_model is None
    assert settings.openrouter_model is None


def test_cors_origins_parses_from_csv_string(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://a,http://b")
    settings = Settings(_env_file=None)
    assert settings.cors_origins == ["http://a", "http://b"]


def test_webhook_retry_delays_parses_from_csv_string(monkeypatch):
    monkeypatch.setenv("WEBHOOK_RETRY_DELAYS", "1,2.5,3")
    settings = Settings(_env_file=None)
    assert settings.webhook_retry_delays == [1.0, 2.5, 3.0]


def test_cors_origins_json_list_form_is_not_supported(monkeypatch):
    # NoDecode (needed to stop pydantic-settings from json.loads()-ing the CSV string before our
    # validator runs) means a JSON-array env value is no longer parsed as JSON either -- it comes
    # through as a single, literal CSV field instead. .env.example only ever uses the CSV form, so
    # this is an accepted tradeoff, documented here rather than silently unsupported.
    monkeypatch.setenv("CORS_ORIGINS", '["http://x"]')
    settings = Settings(_env_file=None)
    assert settings.cors_origins == ['["http://x"]']


def test_real_dotenv_file_matching_env_example_parses_correctly(tmp_path, monkeypatch):
    # The actual startup path that was broken: a real .env, not synthetic env vars.
    # os.environ wins over _env_file in pydantic-settings, so an exported CORS_ORIGINS in the
    # developer's (or CI's) shell would silently make this assert the environment, not the file.
    # conftest's autouse fixture already strips these; state it here too so the test is self-contained.
    for name in ("CORS_ORIGINS", "WEBHOOK_RETRY_DELAYS", "FRONTEND_DIST", "BOT_MODEL", "OPENROUTER_MODEL"):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CORS_ORIGINS=http://localhost:5173\n"
        "WEBHOOK_RETRY_DELAYS=5,30,120\n"
        "FRONTEND_DIST=\n"
        "BOT_MODEL=\n"
        "OPENROUTER_MODEL=\n"
    )
    settings = Settings(_env_file=env_file)
    assert settings.cors_origins == ["http://localhost:5173"]
    assert settings.webhook_retry_delays == [5.0, 30.0, 120.0]
    assert settings.frontend_dist == Path("frontend/dist")
    assert settings.bot_model is None
    assert settings.openrouter_model is None


def test_telegram_bot_token_valid_format(monkeypatch):
    token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefg"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
    settings = Settings(_env_file=None)
    assert settings.telegram_bot_token == token


def test_telegram_bot_token_empty_becomes_none(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    settings = Settings(_env_file=None)
    assert settings.telegram_bot_token is None


def test_telegram_bot_token_invalid_format_raises(monkeypatch):
    import pytest
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "invalid-token")
    with pytest.raises(Exception, match="Invalid Telegram bot token format"):
        Settings(_env_file=None)


def test_telegram_bot_token_not_set_is_none(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    settings = Settings(_env_file=None)
    assert settings.telegram_bot_token is None
