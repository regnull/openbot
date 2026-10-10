"""Bots whose turn runs through a local coding agent CLI instead of OpenBot's own model loop (#196).

The CLI runs in the thread's working directory, its event stream becomes the run events the UI already
shows, and its final result is posted as the bot's reply. base.py holds what the CLIs share, run.py the
runner's side, and each CLI has an adapter.
"""
from openbot.runtime.cli_agents.base import CliAdapter, CliAgentError
from openbot.runtime.cli_agents.claude_code import ClaudeCode

ADAPTERS: dict[str, CliAdapter] = {a.provider: a for a in (ClaudeCode(),)}


def adapter_for(provider: str | None) -> CliAdapter | None:
    return ADAPTERS.get(provider or "")


__all__ = ["ADAPTERS", "CliAdapter", "CliAgentError", "adapter_for"]
