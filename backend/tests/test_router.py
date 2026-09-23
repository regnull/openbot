from openbot.runtime.router import parse_mentions, resolve_targets
from tests.factories import bot_actor, cron_actor, external_actor, human_actor


def mk(handle, enabled=True):
    a = bot_actor(handle)
    a.id, a.enabled = f"id-{handle}", enabled
    return a


YOU = human_actor()
YOU.id = "id-you"
CI = external_actor("ci")
CI.id = "id-ci"
CRON = cron_actor()
CRON.id = "id-cron"
ACTORS = {a.handle: a for a in [mk("eng"), mk("rev"), mk("qa"), mk("off", enabled=False), YOU, CI, CRON]}


def test_parse_mentions():
    assert parse_mentions("hi @eng and @rev, @eng again") == ["eng", "rev"]
    assert parse_mentions("email me@example.com") == []
    # @qa is preceded by ( so it doesn't match begin-of-line/after-space; @nope-bot preceded by a space does.
    assert parse_mentions("(@qa) @nope-bot!") == ["nope-bot"]
    assert parse_mentions("@a") == []


def test_parse_mentions_trailing_punctuation():
    assert parse_mentions("See @eng.") == ["eng"]
    assert parse_mentions("cc @eng-team, then @qa!") == ["eng-team", "qa"]
    assert parse_mentions("read @eng.txt") == []
    assert parse_mentions("me@example.com") == []


def test_explicit_targets_in_order():
    t = resolve_targets(sender=YOU, mentioned_handles=["rev"], to_handles=["eng", "rev"],
                        actors_by_handle=ACTORS, thread_bot_ids=[])
    assert [b.handle for b in t] == ["eng", "rev"]


def test_single_bot_thread_legacy_default():
    t = resolve_targets(sender=YOU, mentioned_handles=[], to_handles=[], actors_by_handle=ACTORS, thread_bot_ids=["id-qa"])
    assert [b.handle for b in t] == ["qa"]


def test_multi_bot_thread_uses_default_bot():
    t = resolve_targets(sender=YOU, mentioned_handles=[], to_handles=[], actors_by_handle=ACTORS,
                        thread_bot_ids=["id-qa", "id-eng"], default_bot_id="id-eng")
    assert [b.handle for b in t] == ["eng"]


def test_explicit_mentions_take_precedence_over_default_bot():
    t = resolve_targets(sender=YOU, mentioned_handles=["qa"], to_handles=[], actors_by_handle=ACTORS,
                        thread_bot_ids=["id-qa", "id-eng"], default_bot_id="id-eng")
    assert [b.handle for b in t] == ["qa"]


def test_cron_self_addressed_reminder_wakes_the_only_bot():
    """A self-scheduled reminder is delivered by @cron, not by the bot that scheduled it, precisely so
    it can still wake that bot: a 'bot' sender excludes itself from candidacy (see
    test_bot_mentions_unknown_default_is_sender), but cron is not a bot."""
    t = resolve_targets(sender=CRON, mentioned_handles=[], to_handles=[], actors_by_handle=ACTORS,
                        thread_bot_ids=["id-qa"], default_bot_id="id-qa")
    assert [b.handle for b in t] == ["qa"]


def test_cron_reminder_routes_to_configured_default_bot():
    t = resolve_targets(sender=CRON, mentioned_handles=[], to_handles=[], actors_by_handle=ACTORS,
                        thread_bot_ids=["id-qa", "id-eng"], default_bot_id="id-eng")
    assert [b.handle for b in t] == ["eng"]


def test_multi_bot_thread_without_configured_default_requires_mention():
    assert resolve_targets(sender=YOU, mentioned_handles=[], to_handles=[], actors_by_handle=ACTORS,
                           thread_bot_ids=["id-qa", "id-eng"]) == []


def test_non_bots_sender_disabled_unknown_removed():
    t = resolve_targets(sender=ACTORS["eng"], mentioned_handles=["eng", "off", "ghost", "you", "ci", "rev"],
                        to_handles=[], actors_by_handle=ACTORS, thread_bot_ids=[])
    assert [b.handle for b in t] == ["rev"]


def test_system_never_routes():
    assert resolve_targets(sender=None, mentioned_handles=["eng"], to_handles=["rev"], actors_by_handle=ACTORS,
                           thread_bot_ids=["id-qa"]) == []


def test_bot_message_wakes_only_the_first_mentioned_bot():
    # "@eng fix these. @qa retest after the fixes." woke both at once and QA had nothing to test. In a
    # bot's reply only the first mention is the hand-off; later @handles are references.
    t = resolve_targets(sender=ACTORS["rev"], mentioned_handles=["eng", "qa"], to_handles=[], actors_by_handle=ACTORS,
                        thread_bot_ids=["id-eng", "id-rev", "id-qa"])
    assert [b.handle for b in t] == ["eng"]


def test_bot_message_first_mention_skips_self_and_disabled():
    t = resolve_targets(sender=ACTORS["rev"], mentioned_handles=["rev", "off", "qa", "eng"], to_handles=[],
                        actors_by_handle=ACTORS, thread_bot_ids=["id-eng", "id-rev", "id-qa"])
    assert [b.handle for b in t] == ["qa"]


def test_human_message_still_wakes_every_mentioned_bot():
    t = resolve_targets(sender=YOU, mentioned_handles=["eng", "qa"], to_handles=[], actors_by_handle=ACTORS,
                        thread_bot_ids=["id-eng", "id-qa"])
    assert [b.handle for b in t] == ["eng", "qa"]


# ---------------------------------------------------------------------------
# Default-bot fallback when a bot mentions an unresolvable handle
# ---------------------------------------------------------------------------

def _coordinator():
    a = bot_actor("chief_of_staff")
    a.id, a.kind, a.enabled = "id-cos", "bot", True
    return a


COS = _coordinator()
ACTORS_WITH_COS = {**ACTORS, COS.handle: COS}


def test_bot_mentions_unknown_handle_falls_back_to_default_bot():
    """Bot mentions @nobody (unknown handle) → default bot picks up the handoff."""
    t = resolve_targets(
        sender=ACTORS["eng"],
        mentioned_handles=["nobody"],
        to_handles=[],
        actors_by_handle=ACTORS_WITH_COS,
        thread_bot_ids=["id-eng", "id-cos"],
        default_bot_id="id-cos",
    )
    assert [b.handle for b in t] == ["chief_of_staff"]


def test_bot_mentions_disabled_bot_falls_back_to_default_bot():
    """Bot mentions a disabled bot → default bot picks up the handoff."""
    t = resolve_targets(
        sender=ACTORS["eng"],
        mentioned_handles=["off"],  # "off" exists but is disabled
        to_handles=[],
        actors_by_handle=ACTORS_WITH_COS,
        thread_bot_ids=["id-eng", "id-cos", "id-off"],
        default_bot_id="id-cos",
    )
    assert [b.handle for b in t] == ["chief_of_staff"]


def test_bot_mentions_self_only_falls_back_to_default_bot():
    """Bot mentions only itself → default bot picks up the handoff."""
    t = resolve_targets(
        sender=ACTORS["eng"],
        mentioned_handles=["eng"],
        to_handles=[],
        actors_by_handle=ACTORS_WITH_COS,
        thread_bot_ids=["id-eng", "id-cos"],
        default_bot_id="id-cos",
    )
    assert [b.handle for b in t] == ["chief_of_staff"]


def test_bot_mentions_valid_bot_no_fallback_needed():
    """Bot mentions a valid, enabled bot → that bot is the target (no fallback)."""
    t = resolve_targets(
        sender=ACTORS["eng"],
        mentioned_handles=["qa"],
        to_handles=[],
        actors_by_handle=ACTORS_WITH_COS,
        thread_bot_ids=["id-eng", "id-qa", "id-cos"],
        default_bot_id="id-cos",
    )
    assert [b.handle for b in t] == ["qa"]


def test_bot_mentions_unknown_no_default_bot_configured():
    """Bot mentions unknown handle, no default bot → result is empty (can't do better)."""
    t = resolve_targets(
        sender=ACTORS["eng"],
        mentioned_handles=["nobody"],
        to_handles=[],
        actors_by_handle=ACTORS,
        thread_bot_ids=["id-eng"],
        default_bot_id=None,
    )
    assert t == []


def test_bot_mentions_unknown_default_is_sender():
    """Bot mentions unknown handle, default bot is the sender itself → empty (can't self-route)."""
    t = resolve_targets(
        sender=ACTORS["eng"],
        mentioned_handles=["nobody"],
        to_handles=[],
        actors_by_handle=ACTORS_WITH_COS,
        thread_bot_ids=["id-eng", "id-cos"],
        default_bot_id="id-eng",
    )
    assert t == []


def test_bot_no_mentions_default_bot_still_receives():
    """Bot sends a message with no mentions at all → default bot receives it."""
    t = resolve_targets(
        sender=ACTORS["eng"],
        mentioned_handles=[],
        to_handles=[],
        actors_by_handle=ACTORS_WITH_COS,
        thread_bot_ids=["id-eng", "id-cos"],
        default_bot_id="id-cos",
    )
    assert [b.handle for b in t] == ["chief_of_staff"]


def test_existing_bot_to_bot_handoff_unchanged():
    """When a bot mentions a valid bot, the existing behavior is preserved."""
    t = resolve_targets(
        sender=ACTORS["rev"],
        mentioned_handles=["eng"],
        to_handles=[],
        actors_by_handle=ACTORS_WITH_COS,
        thread_bot_ids=["id-eng", "id-rev", "id-qa", "id-cos"],
        default_bot_id="id-cos",
    )
    assert [b.handle for b in t] == ["eng"]