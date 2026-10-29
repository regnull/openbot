# OpenBot Terminal Client

A command-line frontend for an running OpenBot server — a terminal alternative to
the web UI. It reuses the **existing** OpenBot REST + Server-Sent-Events API
(`/api/v1/...`); it does not invent a new protocol. The only out-of-tree call is
GitHub issues, which the server does not proxy, so the client talks to
`api.github.com` directly.

## Install

The client lives in the backend package. From the `backend/` directory:

```bash
uv pip install -e .        # or: pip install -e .
```

This installs the `openbot` console script (a click group named `openbot`).

Runtime deps: `httpx` (already in the backend) and `click>=8.1`.

## Connect

Save the server URL once (optional — every command also accepts `--base-url` /
`--api-key`, or the `OPENBOT_URL` / `OPENBOT_API_KEY` env vars):

```bash
openbot connect http://127.0.0.1:8000 --api-key YOUR_KEY
```

The config is stored at `~/.config/openbot-cli/config.json`.

## Commands

| Command | What it does |
| --- | --- |
| `openbot connect <url> [--api-key KEY]` | Save server URL (and optional key) for later commands. |
| `openbot threads [list]` | List threads (title, last activity, default bot, active flag). |
| `openbot thread <id> [watch]` | Print a thread's messages; add `watch` to follow live SSE events. |
| `openbot send <thread> "<msg>" [--bot @handle]` | Post a message; `--bot` (repeatable) `@`-mentions a bot. |
| `openbot bots` | List bots (handle, name, active/disabled state, description). |
| `openbot runs [<thread>]` | List runs; pass a `<thread>` id to scope to one thread. |
| `openbot run <id>` | Show one run and its event log (useful for streaming deltas). |
| `openbot issues [--repo regnull/openbot] [--state open\|closed\|all]` | List GitHub issues (fetched from the GitHub REST API). |

Every command accepts `--json` to emit the raw API payload.

## Examples

```bash
# List threads and pick one
openbot threads

# Read a thread
openbot thread 9f3a1c2e

# Follow it live (prints new messages + run progress as they arrive)
openbot thread 9f3a1c2e watch

# Ask the default bot a question; @-mention the engineer bot explicitly
openbot send 9f3a1c2e "Refactor cli.py and run the tests" --bot @engineer

# See what the bots are doing
openbot bots
openbot runs 9f3a1c2e

# Triage the upstream project
openbot issues --repo regnull/openbot --state open
```

## Streaming / `watch`

`thread <id> watch` opens an SSE connection to `/api/v1/events?thread_id=<id>`
and prints, as they arrive:

- new `message.created` events (formatted like a normal thread message),
- `run.updated` status lines,
- `run.event` streaming text deltas (printed inline, like a typing bot).

Press `Ctrl+C` to disconnect.

## Authentication

If the server requires an API key (`OPENBOT_API_KEY` setting), pass it via
`--api-key`, the `OPENBOT_API_KEY` env var, or `openbot connect --api-key`.
The `/health` probe used by `connect` is unauthenticated, so a connection test
works even before a key is configured.

## GitHub issues

`openbot issues` calls `https://api.github.com/repos/{repo}/issues`. An optional
`GITHUB_TOKEN` (or the OpenBot API key) raises the GitHub rate limit; it is not
required for small lists. Pull requests returned by the GitHub endpoint are
filtered out so you see only issues.

## Testing

Unit tests mock the HTTP client (no live server required):

```bash
cd backend && uv run pytest tests/test_openbot_cli.py
```

## Credits / prior art

The `thread`/`runs`/`watch` model is inspired by run/transcript UIs such as
[harnlang.com sessions](https://harnlang.com/sessions.html) and the
[kodr](https://github.com/paulkohler/kodr) CLI run/scratchpad conventions,
and the session/scratchpad/resume model described at
[terrarium.kohaku-lab.org](https://terrarium.kohaku-lab.org/en/docs/guides/sessions).
Code is original; no third-party code is vendored.
