from sqlalchemy import select

from openbot.db.models import Actor
from openbot.seed import DEMO_BOTS, seed_demo_bots


async def test_seed_once(services):
    services.settings.anthropic_api_key = "k"
    assert await seed_demo_bots(services) == 4
    assert await seed_demo_bots(services) == 0
    async with services.session_factory() as s:
        bots = {a.handle: a for a in (await s.execute(select(Actor).where(Actor.kind == "bot"))).scalars()}
    assert set(bots) == {"chief_of_staff", "engineer", "reviewer", "qa"}
    assert bots["engineer"].bot.provider == "anthropic" and bots["engineer"].bot.model == "claude-sonnet-5"
    assert "run_shell" in bots["engineer"].bot.tool_names and "write_file" not in bots["reviewer"].bot.tool_names
    assert all(services.registry.has(t) for b in DEMO_BOTS for t in b["tool_names"])


async def test_seed_skipped_without_provider(services):
    assert await seed_demo_bots(services) == 0
