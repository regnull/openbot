"""Click-based command line interface for the OpenBot terminal client.

Commands mirror the core web-UI flows against a running OpenBot server:

    openbot connect <url> [--api-key KEY]   Save connection settings
    openbot threads [list]                  List threads
    openbot thread <id> [watch]             Show a thread (or live-follow it)
    openbot send <thread> "<msg>" [--bot @h] Post a message, optionally @-ing a bot
    openbot bots                           List bots
    openbot runs [<thread>]                List runs (optionally for one thread)
    openbot issues [--repo regnull/openbot] List GitHub issues

This is a frontend only — every command calls the existing ``/api/v1`` REST and
SSE endpoints. See README.md in this package for a full usage guide.
"""

from __future__ import annotations

import json
import os
import sys

import click

from openbot_cli.client import GitHubIssuesClient, OpenBotClient
from openbot_cli.config import (
    CONFIG_PATH,
    ConfigError,
    load_config,
    resolve,
    save_config,
)
from openbot_cli.formatting import (
    format_bots,
    format_issues,
    format_run_detail,
    format_runs,
    format_thread_detail,
    format_threads,
)


def _make_client(base_url: str, api_key: str | None) -> OpenBotClient:
    return OpenBotClient(base_url=base_url, api_key=api_key)


@click.group()
@click.option("--base-url", envvar="OPENBOT_URL", default=None, help="OpenBot base URL (env: OPENBOT_URL).")
@click.option("--api-key", envvar="OPENBOT_API_KEY", default=None, help="API key (env: OPENBOT_API_KEY).")
@click.pass_context
def cli(ctx: click.Context, base_url: str | None, api_key: str | None) -> None:
    """OpenBot terminal client — talk to your bots and threads from the shell."""
    ctx.ensure_object(dict)
    # If a client was injected (tests, embedding, DI), use it as-is and skip the
    # config-resolve + client-build path so the injected one is not clobbered.
    if "client" in ctx.obj:
        return
    try:
        url, key = resolve(base_url, api_key)
    except ConfigError as e:
        raise click.ClickException(str(e)) from e
    ctx.obj["base_url"] = url
    ctx.obj["api_key"] = key
    ctx.obj["client"] = _make_client(url, key)


@cli.command("connect")
@click.argument("url", required=False)
@click.option("--api-key", default=None, help="API key to store alongside the URL.")
@click.option("--config", "config_path", default=None, type=click.Path(), help="Config file (advanced).")
def connect(url: str | None, api_key: str | None, config_path: str | None) -> None:
    """Save the OpenBot server URL (and optional API key) for future commands."""
    path = CONFIG_PATH if config_path is None else __import__("pathlib").Path(config_path)
    data = load_config(path)
    if url:
        data["base_url"] = url.rstrip("/")
    if api_key:
        data["api_key"] = api_key
    saved = save_config(data, path)
    click.echo(f"Saved connection to {data['base_url']} ({saved})")


@cli.command("threads")
@click.argument("subcommand", required=False, type=click.Choice(["list"]))
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
@click.pass_context
def threads(ctx: click.Context, subcommand: str | None, as_json: bool) -> None:
    """List threads (alias: `threads list`)."""
    client: OpenBotClient = ctx.obj["client"]
    data = client.list_threads()
    if as_json:
        click.echo(json.dumps(data, indent=2, default=str))
        return
    click.echo(format_threads(data))


@cli.command("thread")
@click.argument("thread_id")
@click.argument("subcommand", required=False, type=click.Choice(["watch"]))
@click.option("--limit", default=50, show_default=True, help="Messages to load.")
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
@click.pass_context
def thread(ctx: click.Context, thread_id: str, subcommand: str | None, limit: int, as_json: bool) -> None:
    """Show a thread's messages. Add `watch` to follow live events."""
    client: OpenBotClient = ctx.obj["client"]
    detail = client.get_thread(thread_id, limit=limit)
    if as_json:
        click.echo(json.dumps(detail, indent=2, default=str))
        return
    click.echo(format_thread_detail(detail))
    if subcommand == "watch":
        click.echo("\n--- watching (Ctrl+C to stop) ---")
        try:
            _watch(client, thread_id)
        except KeyboardInterrupt:
            click.echo("\nDisconnected.")


def _watch(client: OpenBotClient, thread_id: str) -> None:
    for item in client.stream_events(thread_id=thread_id):
        event = item.get("event", "?")
        data = item.get("data", item)
        if event == "message.created":
            from openbot_cli.formatting import format_message

            msg = data if isinstance(data, dict) else {}
            click.echo(format_message(msg))
            click.echo("─" * 60)
        elif event == "run.updated":
            status = (data or {}).get("status", "?")
            click.echo(f"[run] {status}")
        elif event == "run.event":
            payload = (data or {}).get("payload") or {}
            delta = payload.get("delta")
            if delta:
                click.echo(delta, nl=False)
        else:
            click.echo(f"[{event}]")


@cli.command("send")
@click.argument("thread_id")
@click.argument("message")
@click.option("--bot", "bots", multiple=True, help="Bot handle to @-mention (repeatable).")
@click.option("--from", "sender", default=None, help="Sender handle (default: you/human).")
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
@click.pass_context
def send(ctx: click.Context, thread_id: str, message: str, bots: tuple[str, ...],
         sender: str | None, as_json: bool) -> None:
    """Send MESSAGE to THREAD_ID. Use --bot @handle to address a bot."""
    client: OpenBotClient = ctx.obj["client"]
    to = [b.lstrip("@") for b in bots]
    result = client.send_message(thread_id, message, to=to, sender=sender)
    if as_json:
        click.echo(json.dumps(result, indent=2, default=str))
        return
    msg = result["message"]
    click.echo(f"Posted as {msg['sender_name']} at {msg.get('created_at')}")
    if result.get("addressed"):
        click.echo(f"Addressed: {', '.join('@' + a for a in result['addressed'])}")
    if result.get("unaddressed"):
        click.echo("(no bots were addressed — message may go unread)")


@cli.command("bots")
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
@click.pass_context
def bots(ctx: click.Context, as_json: bool) -> None:
    """List bots on the connected server."""
    client: OpenBotClient = ctx.obj["client"]
    data = client.list_bots()
    if as_json:
        click.echo(json.dumps(data, indent=2, default=str))
        return
    click.echo(format_bots(data))


@cli.command("runs")
@click.argument("thread_id", required=False)
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
@click.pass_context
def runs(ctx: click.Context, thread_id: str | None, as_json: bool) -> None:
    """List runs, optionally for one THREAD_ID."""
    client: OpenBotClient = ctx.obj["client"]
    data = client.list_runs(thread_id)
    if as_json:
        click.echo(json.dumps(data, indent=2, default=str))
        return
    click.echo(format_runs(data))


@cli.command("run")
@click.argument("run_id")
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
@click.pass_context
def run(ctx: click.Context, run_id: str, as_json: bool) -> None:
    """Show one RUN_ID with its event log."""
    client: OpenBotClient = ctx.obj["client"]
    detail = client.get_run(run_id)
    if as_json:
        click.echo(json.dumps(detail, indent=2, default=str))
        return
    click.echo(format_run_detail(detail))


@cli.command("issues")
@click.option("--repo", default="regnull/openbot", show_default=True, help="owner/name repository.")
@click.option("--state", default="open", show_default=True, type=click.Choice(["open", "closed", "all"]))
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
@click.pass_context
def issues(ctx: click.Context, repo: str, state: str, as_json: bool) -> None:
    """List GitHub issues for REPO (fetched from the GitHub REST API)."""
    token = ctx.obj.get("api_key") or os.environ.get("GITHUB_TOKEN")
    client = GitHubIssuesClient(token=token)
    data = client.list_issues(repo=repo, state=state)
    # GitHub's issues endpoint also returns PRs; filter them out for a clean list.
    data = [it for it in data if "pull_request" not in it]
    if as_json:
        click.echo(json.dumps(data, indent=2, default=str))
        return
    click.echo(format_issues(data))


def main() -> int:
    """Console-script entry point."""
    try:
        cli()  # pragma: no cover - click drives sys.exit
    except click.ClickException as e:
        e.show()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
