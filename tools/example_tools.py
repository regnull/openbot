"""Example OpenBot tool plugin. Every module-level LangChain tool in this directory is loaded."""
from datetime import datetime, timezone

from langchain.tools import tool


@tool
def get_time() -> str:
    """Return the current UTC time in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


@tool
def word_count(text: str) -> int:
    """Count the words in the given text."""
    return len(text.split())
