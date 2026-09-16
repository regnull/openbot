from sqlalchemy import select

from openbot.db.models import Actor
from openbot.runtime.providers import effective_bot_profile
from openbot.seed import DEMO_BOTS, seed_demo_bots


async def test_seed_once(services):
    services.settings.openrouter_api_key = "k"
    assert await seed_demo_bots(services) == 4
    assert await seed_demo_bots(services) == 0
    async with services.session_factory() as s:
        bots = {a.handle: a for a in (await s.execute(select(Actor).where(Actor.kind == "bot"))).scalars()}
    assert set(bots) == {"chief_of_staff", "engineer", "reviewer", "qa"}
    # Demo bots default to provider "auto" so they keep working as keys are added/removed/changed.
    assert bots["engineer"].bot.provider == "auto"
    assert effective_bot_profile(bots["engineer"].bot, services.settings) == ("openrouter", "openai/gpt-4o-mini")
    assert "run_shell" in bots["engineer"].bot.tool_names and "write_file" not in bots["reviewer"].bot.tool_names
    assert all(services.registry.has(t) for b in DEMO_BOTS for t in b["tool_names"])


async def test_seed_skipped_without_provider(services):
    assert await seed_demo_bots(services) == 0


async def test_seed_uses_configured_bot_model(services):
    services.settings.openrouter_api_key = "k"
    services.settings.bot_model = "google/gemini-2.0-flash-001"
    assert await seed_demo_bots(services) == 4
    async with services.session_factory() as s:
        bots = {a.handle: a for a in (await s.execute(select(Actor).where(Actor.kind == "bot"))).scalars()}
    assert bots["chief_of_staff"].bot.provider == "auto"
    assert effective_bot_profile(bots["chief_of_staff"].bot, services.settings) == ("openrouter", "google/gemini-2.0-flash-001")


def test_chief_of_staff_delegates_in_the_same_thread():
    chief = next(b for b in DEMO_BOTS if b["handle"] == "chief_of_staff")
    assert "in this same thread" in chief["instructions"]
    assert "Never use start_thread" in chief["instructions"]


async def test_sync_updates_existing_demo_bots_without_touching_the_rest(services):
    """The seed skips existing rows, so a redesigned team never reaches a running install. Sync
    rewrites the demo bots' instructions, tools, approval tools and model settings from DEMO_BOTS,
    leaves their provider/model pin alone, and ignores bots that are not part of the demo team."""
    from openbot.db.models import Actor, BotProfile
    from openbot.seed import sync_demo_bots
    services.settings.openrouter_api_key = "k"
    assert await seed_demo_bots(services) == 4
    async with services.session_factory() as s:
        chief = (await s.execute(select(Actor).where(Actor.handle == "chief_of_staff"))).scalar_one()
        chief.bot.instructions, chief.bot.tool_names, chief.bot.model_settings = "old", ["read_file"], {}
        chief.bot.provider, chief.bot.model = "ollama", "qwen3.6"
        s.add(Actor(kind="bot", handle="custom", name="Custom", bot=BotProfile(instructions="mine", tool_names=["run_shell"])))
        await s.commit()
    assert await sync_demo_bots(services) == 4
    async with services.session_factory() as s:
        chief = (await s.execute(select(Actor).where(Actor.handle == "chief_of_staff"))).scalar_one()
        spec = next(b for b in DEMO_BOTS if b["handle"] == "chief_of_staff")
        assert chief.bot.instructions == spec["instructions"] and chief.bot.tool_names == spec["tool_names"]
        assert chief.bot.model_settings == spec["model_settings"]
        assert (chief.bot.provider, chief.bot.model) == ("ollama", "qwen3.6")      # the operator's pin survives
        custom = (await s.execute(select(Actor).where(Actor.handle == "custom"))).scalar_one()
        assert custom.bot.instructions == "mine" and custom.bot.tool_names == ["run_shell"]
