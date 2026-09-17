from openbot.runtime.router import parse_mentions, resolve_targets
from tests.factories import bot_actor, external_actor, human_actor


def mk(handle, enabled=True):
    a = bot_actor(handle)
    a.id, a.enabled = f"id-{handle}", enabled
    return a


YOU = human_actor()
YOU.id = "id-you"
CI = external_actor("ci")
CI.id = "id-ci"
ACTORS = {a.handle: a for a in [mk("eng"), mk("rev"), mk("qa"), mk("off", enabled=False), YOU, CI]}


def test_parse_mentions():
    # Middle-of-line mentions no longer trigger
    assert parse_mentions("hi @eng and @rev, @eng again") == []
    # Email addresses still excluded
    assert parse_mentions("email me@example.com") == []
    # Middle-of-line parenthetical mentions no longer trigger
    assert parse_mentions("(@qa) @nope-bot!") == []
    # Too-short handle still excluded
    assert parse_mentions("@a") == []


def test_parse_mentions_line_start():
    # At very start of message
    assert parse_mentions("@reviewer, review this") == ["reviewer"]
    # After newline
    assert parse_mentions("Line 1\n@reviewer do it") == ["reviewer"]
    # After newline — multple mentions on same line after line-start only match the first
    assert parse_mentions("first line\n@eng @rev") == ["eng"]
    # Sole content at line start
    assert parse_mentions("@eng") == ["eng"]


def test_parse_mentions_middle_of_line_no_match():
    # Middle of line should not match
    assert parse_mentions("when you are done, call @reviewer") == []
    assert parse_mentions("See @eng.") == []
    assert parse_mentions("cc @eng-team, then @qa!") == []


def test_parse_mentions_non_mention_at_line_start():
    # Even at line start, email/filename exclusions remain
    assert parse_mentions("me@example.com") == []
    assert parse_mentions("read @eng.txt") == []
    # Email at line start of its own line — not a mention
    assert parse_mentions("some text\nme@example.com") == []
    # @-prefixed handle after non-mention text on same line = no match
    assert parse_mentions("me@example.com\nand then @eng") == []
    # Line-start mention after an email-only line
    assert parse_mentions("me@example.com\n@eng review this") == ["eng"]


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