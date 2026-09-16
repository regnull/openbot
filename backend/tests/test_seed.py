from sqlalchemy import select

from openbot.db.models import Actor
from openbot.seed import DEMO_BOTS, seed_demo_bots


async def test_seed_once(services):
    services.settings.openrouter_api_key = "k"
    assert await seed_demo_bots(services) == 4
    assert await seed_demo_bots(services) == 0
    async with services.session_factory() as s:
        bots = {a.handle: a for a in (await s.execute(select(Actor).where(Actor.kind == "bot"))).scalars()}
    assert set(bots) == {"chief_of_staff", "engineer", "reviewer", "qa"}
    assert bots["engineer"].bot.provider == "openrouter" and bots["engineer"].bot.model == "openai/gpt-4o-mini"
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
    assert bots["chief_of_staff"].bot.provider == "openrouter"
    assert bots["chief_of_staff"].bot.model == "google/gemini-2.0-flash-001"


def test_chief_of_staff_delegates_in_the_same_thread():
    chief = next(b for b in DEMO_BOTS if b["handle"] == "chief_of_staff")
    assert "in this same thread" in chief["instructions"]
    assert "Never use start_thread" in chief["instructions"]
