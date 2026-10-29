"""Human-readable rendering helpers for OpenBot API payloads.

Pure functions: no I/O, no terminal side effects beyond what the caller prints.
Keeping them separate makes them trivially unit-testable without a server.
"""

from __future__ import annotations

from datetime import UTC, datetime


def format_ts(value: str | None) -> str:
    """Render an ISO timestamp in the local timezone, or a dash when missing."""
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, OSError):
        return value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


def format_threads(threads: list[dict]) -> str:
    if not threads:
        return "No threads found."
    lines = []
    for t in threads:
        title = (t.get("title") or "(untitled)")[:60]
        updated = format_ts(t.get("last_message_at") or t.get("updated_at"))
        bot = t.get("default_bot_handle") or "—"
        active = "⚡" if t.get("active") else " "
        tid = t["id"]
        lines.append(f"{active} {tid[:8]}  {title:<60s}  {updated}  @{bot}")
    return "\n".join(lines)


def format_thread_detail(detail: dict) -> str:
    title = detail.get("title") or "(untitled)"
    bot = detail.get("default_bot_handle") or "—"
    out = [f"Thread: {title}", f"Default bot: @{bot}"]
    if detail.get("participants"):
        parts = ", ".join(f"@{p['handle']} ({p['kind']})" for p in detail["participants"])
        out.append(f"Participants: {parts}")
    if detail.get("has_more"):
        out.append("(more messages available — use --limit to load more)")
    out.append("─" * 60)
    for m in detail.get("messages", []):
        out.append(format_message(m))
        out.append("─" * 60)
    return "\n".join(out)


def format_message(m: dict) -> str:
    sender = m.get("sender_name") or m.get("sender_actor_id", "?")
    ts = format_ts(m.get("created_at"))
    content = m.get("content", "")
    header = f"[{ts}] {sender}"
    if m.get("mentions"):
        header += " → " + " ".join(f"@{h}" for h in m["mentions"])
    if len(content) > 500:
        content = content[:500] + f"\n... [{len(content) - 500} more chars]"
    return f"{header}:\n{content}"


def format_bots(bots: list[dict]) -> str:
    if not bots:
        return "No bots found."
    lines = []
    for b in bots:
        state = "active" if b.get("active") else ("disabled" if not b.get("enabled") else "idle")
        lines.append(f"{b.get('icon', '🤖')} {b['handle']:<20s} {b.get('name', ''):<24s} [{state}]")
        if b.get("description"):
            lines.append(f"    {b['description']}")
    return "\n".join(lines)


def format_runs(runs: list[dict]) -> str:
    if not runs:
        return "No runs found."
    lines = []
    for r in runs:
        created = format_ts(r.get("created_at"))
        actor = r.get("actor_id", "?")[:8]
        status = r.get("status", "?")
        tokens = r.get("total_tokens")
        tok = f"{tokens} tok" if tokens is not None else "— tok"
        cost = r.get("cost_usd")
        cost_s = f"${cost:.4f}" if cost is not None else "—"
        lines.append(
            f"{r['id'][:8]}  {created}  actor={actor}  {status:<14s} {tok:<12s} {cost_s}"
        )
    return "\n".join(lines)


def format_run_detail(run: dict) -> str:
    out = [
        f"Run: {run['id']}",
        f"Status: {run.get('status')}",
        f"Actor: {run.get('actor_id')}",
        f"Created: {format_ts(run.get('created_at'))}",
        f"Started: {format_ts(run.get('started_at'))}",
        f"Finished: {format_ts(run.get('finished_at'))}",
        f"Tokens: {run.get('total_tokens')}  Cost: {run.get('cost_usd')}",
    ]
    if run.get("error"):
        out.append(f"Error: {run['error']}")
    events = run.get("events") or []
    if events:
        out.append("─" * 60)
        out.append(f"Events ({len(events)}):")
        for ev in events:
            out.append(f"  [{ev.get('seq')}] {ev.get('type')}: {short_payload(ev.get('payload'))}")
    return "\n".join(out)


def short_payload(payload: dict | None) -> str:
    if not payload:
        return ""
    # Surface the streaming text delta when present; otherwise a compact view.
    if "delta" in payload:
        return str(payload["delta"])[:120]
    if "content" in payload:
        return str(payload["content"])[:120]
    return str(payload)[:120]


def format_issues(issues: list[dict]) -> str:
    if not issues:
        return "No issues found."
    lines = []
    for it in issues:
        number = it.get("number")
        title = (it.get("title") or "").replace("\n", " ")
        labels = ", ".join(lbl.get("name", "") for lbl in it.get("labels", []))
        state = it.get("state", "?")
        lines.append(f"#{number} [{state}] {title}")
        if labels:
            lines.append(f"    labels: {labels}")
    return "\n".join(lines)
