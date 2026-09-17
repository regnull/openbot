"""The one key that protects every secret stored in the database.

Provider API keys, MCP server headers and environment, and MCP OAuth tokens are all Fernet-encrypted
with it. It comes from `SECRET_KEY`, or is generated once into `SECRET_KEY_FILE` (owner-only). The
older `MCP_TOKEN_KEY` / `MCP_TOKEN_KEY_FILE` names are honoured so credentials stored before the
rename stay readable.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)


def resolve_secret_key(settings) -> str:
    explicit = settings.secret_key or getattr(settings, "mcp_token_key", None)
    if explicit:
        return explicit
    new_file = Path(settings.secret_key_file)
    legacy_file = Path(getattr(settings, "mcp_token_key_file", "") or "")
    for path in (new_file, legacy_file):
        if str(path) and path.is_file():
            return path.read_text(encoding="utf-8").strip()
    key = Fernet.generate_key().decode()
    new_file.parent.mkdir(parents=True, exist_ok=True)
    new_file.write_text(key, encoding="utf-8")
    os.chmod(new_file, 0o600)
    log.info("generated the secret key at %s", new_file)
    return key


class SecretBox:
    """Encrypts and decrypts stored secrets; the key is resolved on first use, so an install with no
    secrets never needs (or writes) one."""

    def __init__(self, key: str | Callable[[], str]) -> None:
        self._key = key
        self._fernet: Fernet | None = None

    @property
    def fernet(self) -> Fernet:
        if self._fernet is None:
            key = self._key() if callable(self._key) else self._key
            self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
        return self._fernet

    def encrypt(self, text: str) -> str:
        return self.fernet.encrypt(text.encode()).decode()

    def decrypt(self, token: str) -> str | None:
        """None when the token cannot be read with this key (rotated or lost)."""
        try:
            return self.fernet.decrypt(token.encode()).decode()
        except (InvalidToken, ValueError):
            return None
