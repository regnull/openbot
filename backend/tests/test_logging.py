"""Diagnostic logging: a detailed, timestamped log file so that "the bot cannot see my files" style
problems can be traced after the fact (which workspace root was resolved, which directory each run
used, what every tool call asked for and returned)."""
import logging
from pathlib import Path

import pytest
from asgi_lifespan import LifespanManager

from openbot.config import Settings
from openbot.logsetup import configure_logging
from openbot.main import create_app


def _file_handlers(logger: logging.Logger) -> list[logging.Handler]:
    return [h for h in logger.handlers if isinstance(h, logging.FileHandler)]


def test_configure_logging_writes_debug_detail_to_file_and_honours_console_level(settings):
    settings.log_level = "WARNING"
    configure_logging(settings)
    log = logging.getLogger("openbot.test_logging")
    log.debug("debug-detail-line")
    log.warning("warning-line")
    for h in logging.getLogger("openbot").handlers:
        h.flush()
    text = Path(settings.log_file).read_text()
    assert "debug-detail-line" in text and "warning-line" in text
    # timestamped and named, so lines from different components can be correlated
    assert "openbot.test_logging" in text
    console = [h for h in logging.getLogger("openbot").handlers if not isinstance(h, logging.FileHandler)]
    assert console and all(h.level == logging.WARNING for h in console)


def test_configure_logging_twice_does_not_stack_handlers(settings):
    configure_logging(settings)
    configure_logging(settings)
    root = logging.getLogger("openbot")
    assert len(_file_handlers(root)) == 1
    assert len([h for h in root.handlers if not isinstance(h, logging.FileHandler)]) == 1


def test_configure_logging_creates_parent_directory(settings, tmp_path):
    settings.log_file = tmp_path / "nested" / "dir" / "openbot.log"
    configure_logging(settings)
    assert settings.log_file.exists()


@pytest.mark.parametrize("access_propagates", [True, False])
def test_uvicorn_lines_are_mirrored_to_file_exactly_once(settings, access_propagates, monkeypatch):
    # Under uvicorn, uvicorn.access has its own handler and propagate=False; outside it, it propagates
    # to the parent like any logger. Both must land in the file exactly once.
    monkeypatch.setattr(logging.getLogger("uvicorn.access"), "propagate", access_propagates)
    configure_logging(settings)
    # uvicorn sets these levels itself when it owns the process; outside it they are NOTSET.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        monkeypatch.setattr(logging.getLogger(name), "level", logging.INFO)
    logging.getLogger("uvicorn.error").info("uvicorn-error-line")
    logging.getLogger("uvicorn.access").info("uvicorn-access-line")
    for name in ("openbot", "uvicorn", "uvicorn.access"):
        for h in logging.getLogger(name).handlers:
            h.flush()
    text = Path(settings.log_file).read_text()
    assert text.count("uvicorn-error-line") == 1
    assert text.count("uvicorn-access-line") == 1


def test_empty_log_file_env_uses_default(monkeypatch):
    monkeypatch.setenv("LOG_FILE", "")
    s = Settings(_env_file=None)
    assert s.log_file == Path("logs/openbot.log")
    assert s.log_level == "INFO"


async def test_startup_logs_resolved_configuration(settings, caplog):
    caplog.set_level(logging.INFO, logger="openbot")
    app = create_app(settings)
    async with LifespanManager(app):
        pass
    startup = [r.getMessage() for r in caplog.records if r.getMessage().startswith("startup:")]
    assert len(startup) == 1
    line = startup[0]
    assert f"workspace_root={settings.workspace_root.resolve()}" in line
    assert f"tools_dir={settings.tools_dir.resolve()}" in line
    assert "cwd=" in line and "database_url=" in line and "log_file=" in line
