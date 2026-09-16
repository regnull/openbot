"""Diagnostic logging.

Two sinks hang off the ``openbot`` logger:

* the console, at ``LOG_LEVEL`` (INFO by default) in uvicorn's terse style, and
* a rotating file at ``LOG_FILE`` (``./logs/openbot.log`` by default) that always records DEBUG
  detail with timestamps and logger names.

The file is what you reach for after the fact: it records the resolved configuration at startup,
every run's bot/thread/working directory/model, each tool call and its result, and (at DEBUG) the
full system prompt a bot was given -- enough to answer "why did the bot not see my files?" without
reproducing the run. uvicorn's own loggers are mirrored into the same file so HTTP errors and
reloads line up with bot activity.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

FILE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
CONSOLE_FORMAT = "%(levelname)s:     %(message)s"
MAX_BYTES = 10 * 1024 * 1024
BACKUP_COUNT = 5
MIRRORED_LOGGER = "uvicorn"


class _OpenBotFileHandler(RotatingFileHandler):
    """Marker subclass so repeated configure_logging() calls can find and replace our handler."""


class _OpenBotConsoleHandler(logging.StreamHandler):
    """Marker subclass, same reason."""


def configure_logging(settings) -> None:
    """Idempotent: replaces handlers installed by an earlier call instead of stacking them, so
    repeated create_app() calls (tests, reloads) keep exactly one console and one file sink."""
    level = logging.getLevelNamesMapping().get(str(settings.log_level).upper(), logging.INFO)
    root = logging.getLogger("openbot")
    root.setLevel(logging.DEBUG)      # sinks filter; the file always gets DEBUG detail

    for h in list(root.handlers):
        if isinstance(h, _OpenBotFileHandler | _OpenBotConsoleHandler):
            root.removeHandler(h)
            h.close()
    console = _OpenBotConsoleHandler()
    console.setLevel(level)
    console.setFormatter(logging.Formatter(CONSOLE_FORMAT))
    root.addHandler(console)

    file_handler = _file_handler(Path(settings.log_file))
    root.addHandler(file_handler)
    _mirror(logging.getLogger(MIRRORED_LOGGER), file_handler)
    # uvicorn's default config gives uvicorn.access its own handler with propagate=False, so records
    # never reach the parent; attach directly in that case only (attaching when it does propagate,
    # e.g. outside a uvicorn process, would record every access line twice).
    access = logging.getLogger(f"{MIRRORED_LOGGER}.access")
    _mirror(access, file_handler if not access.propagate else None)


def _mirror(logger: logging.Logger, handler: _OpenBotFileHandler | None) -> None:
    for h in list(logger.handlers):
        if isinstance(h, _OpenBotFileHandler):
            logger.removeHandler(h)
    if handler is not None:
        logger.addHandler(handler)


def _file_handler(path: Path) -> _OpenBotFileHandler:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = _OpenBotFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(FILE_FORMAT))
    return handler
