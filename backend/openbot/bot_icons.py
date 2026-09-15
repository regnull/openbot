from __future__ import annotations

DEFAULT_BOT_ICON = "robot"
BOT_ICON_KEYS: tuple[str, ...] = (
    "robot",
    "briefcase",
    "code",
    "search",
    "test-tube",
    "shield",
    "sparkles",
    "chat",
    "brain",
    "rocket",
)


def validate_bot_icon(icon: str) -> str:
    if icon not in BOT_ICON_KEYS:
        raise ValueError(f"icon must be one of: {', '.join(BOT_ICON_KEYS)}")
    return icon
