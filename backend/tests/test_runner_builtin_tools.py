import pytest

from openbot.runtime import runner as runner_mod
from tests.factories import bot_actor


@pytest.mark.asyncio
async def test_build_agent_passes_provider_builtin_tools_to_create_agent(services, monkeypatch):
    """A pre-bound tool on the model is lost when create_agent rebinds the agent's tools, so the hosted web
    search tool has to travel in the agent's tool list."""
    services.settings.anthropic_api_key = "k"
    captured = {}

    def fake_create_agent(model, tools, **kwargs):
        captured["tools"] = tools
        return object()

    monkeypatch.setattr(runner_mod, "create_agent", fake_create_agent)
    bot = bot_actor("bob", provider="anthropic", model="claude-sonnet-5", model_settings={"web_search": True}, tool_names=[])
    bot.id = "b1"
    services.runner._build_agent(bot, "system prompt")
    assert {"type": "web_search_20250305", "name": "web_search"} in captured["tools"]

    captured.clear()
    plain = bot_actor("bill", provider="anthropic", model="claude-sonnet-5", model_settings={}, tool_names=[])
    plain.id = "b2"
    services.runner._build_agent(plain, "system prompt")
    assert not [t for t in captured["tools"] if isinstance(t, dict)]
