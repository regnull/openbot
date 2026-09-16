# OpenBot

OpenBot is an open-source, self-hosted platform for running a team of persistent AI bots. Each
bot has a name, a description, and instructions that govern its behavior. Bots talk to humans and
to each other in shared threads, use pluggable tools, keep long-term memory, and can be reached by
external systems over HTTP. Chains of bots form workflows: for example, a Chief of Staff bot
delegates to an Engineer bot, the Engineer opens a pull request, a Reviewer bot reviews it, and a
QA bot tests it, asks a human for approval, and merges.

Everything in OpenBot — bots, humans, and external systems — is an **actor** with a persistent
inbox. Actors post messages into each other's inboxes through shared threads; a bot actor wakes up
when mail arrives, runs an LLM-driven agent loop with tools and memory, and replies, which in turn
delivers new mail and can wake the next bot. This uniform model is what lets a human, a bot, and a
webhook-driven external system all participate in the same conversation the same way.

## Features

- **Actor model runtime**: bots, humans, and external systems are all actors with inboxes; one
  run at a time per bot, with a global concurrency cap.
- **Multi-bot workflows**: user messages without an explicit bot mention go to the thread default bot (`@chief_of_staff` unless changed); bots hand off to each other with `@mention`, with a hop limit to
  prevent runaway bot-to-bot loops.
- **Tools**: built-in shell/file/HTTP tools rooted at a workspace directory, plus a plugin
  directory of your own Python tools. `run_shell` is **not** sandboxed — see
  [Trust model / security](#trust-model--security).
- **Memory**: per-bot long-term memory (LangMem) that bots can search and update, with automatic
  background reflection after each run.
- **Approvals and questions**: bots can ask a human before taking a sensitive action
  (`ask_human`, or per-tool approval flags); the run pauses until a human answers.
- **External actors**: register an external system as an actor; it exchanges mail with the rest
  of OpenBot over a signed webhook or by polling the REST API.
- **Live UI**: React frontend with an Inbox, Threads, Bots, and Settings, updated over SSE.
- **Any SQL database**: SQLite by default, Postgres by changing one URL.
- **LangSmith tracing** out of the box.

## Quick start

Prerequisites: Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node 24+ with
[pnpm](https://pnpm.io/) 10, and an OpenRouter API key (recommended), or another
LLM provider API key (OpenAI, Anthropic, or xAI).

```bash
make setup            # uv sync (backend), pnpm install (frontend), copy .env.example -> .env
$EDITOR .env           # add OPENROUTER_API_KEY (recommended) or another provider key
make dev               # backend on :8000, frontend dev server on :5173
```

Open http://localhost:5173. The Vite dev server proxies `/api` to the backend, so no CORS setup
is needed in development.

On first start (with a provider key configured and an empty bot table) OpenBot seeds the human
actor `@you` and four demo bots: `chief_of_staff`, `engineer`, `reviewer`, `qa`.

For a single-process, production-style run that serves the built frontend from the backend on
port 8000:

```bash
make run               # builds frontend/dist, then serves it from the FastAPI app on :8000
```

## Demo walkthrough

The seeded bots are set up to run a small software workflow end to end against a real git
repository, using the [`gh`](https://cli.github.com/) CLI.

1. Clone a repository you can push to into `workspace/` (the default `WORKSPACE_ROOT`), and make
   sure `gh auth status` succeeds from that directory — the bots shell out to `git` and `gh`.
2. Start OpenBot (`make dev` or `make run`) and open the UI.
3. Start a new thread (its default bot is `@chief_of_staff` unless you change it), then send:

   > Add a `--version` flag to the CLI and open a PR.

4. Watch the hand-off: Chief of Staff delegates to `@engineer`, who implements the change, opens
   a PR, and mentions `@reviewer`; the reviewer reviews the diff with `gh pr diff` and mentions
   `@qa` (or sends feedback back to `@engineer`); QA checks out the branch, runs the tests, and
   asks you for approval before merging.
5. When QA's question shows up in the **Inbox**, open it and approve. QA merges the PR and
   reports back.

## Concepts

| Term | Meaning |
|---|---|
| **Actor** | Any participant with a persistent inbox: a bot, the human (`@you`), or an external system. |
| **Inbox** | An actor's queue of items (`message`, `question`, `resume`) waiting to be processed or acknowledged. |
| **Thread** | A conversation with a set of actor participants, a default bot, and a working directory for thread tools. Messages are posted into a thread and routed to inbox items for explicit bot mentions, or to the default bot when a user message has no explicit bot mention. |
| **Run** | One execution of a bot's agent loop, triggered by a batch of queued messages or by resuming after a question/approval. |
| **Hop** | A counter on bot-to-bot messages; bot replies increment it, human/external messages reset it to 0. Once `MAX_BOT_HOPS` is reached, further bot-to-bot delegation is blocked in that thread until a human message resets it. |
| **Approval** | A pause requested by a tool (`ask_human`, or a tool flagged for approval) that turns into a `question` inbox item for the human and any external participants; the bot resumes once it is answered. |
| **Memory** | Per-bot long-term memory in the LangGraph store, searchable and updatable by the bot, refreshed by a background reflection step after each run. Nothing is ever purged. |

## Trust model / security

OpenBot is built for a **single trusted operator running it on their own machine**. There is no
login, no user accounts, and no privilege separation. Anyone who can reach the HTTP port and anyone
who can get a bot to run a tool has, in practice, the privileges of the server process. Read this
before exposing OpenBot to a network or pointing a bot at untrusted input.

- **`run_shell` is not sandboxed.** It executes arbitrary commands with `bash -lc` as the user
  running the server, with that user's full filesystem and network access. The only thing the
  thread working directory gives you is the command's *starting working directory*: `cd /`, `../`, absolute paths
  and anything else all work normally. It also inherits the server's environment, including the
  provider API keys loaded from `.env`, so a command can read or exfiltrate them. There is no
  container, no chroot, no seccomp, and no allowlist — giving a bot `run_shell` is equivalent to
  giving whoever can talk to that bot a shell on the host.
- **Only the file tools are path-confined.** `read_file`, `write_file` and `list_files` resolve
  every path against the thread working directory (the selected subdirectory of `WORKSPACE_ROOT`,
  or `WORKSPACE_ROOT` itself by default) and reject anything that escapes it (`../`, absolute paths,
  symlinks out). That confinement is real, but it protects nothing once `run_shell` is also
  enabled.
- **`http_request` and `fetch_url` are unrestricted.** Any URL, any method — including private
  network ranges and `localhost`. A bot can therefore call OpenBot's own API on the loopback
  interface, which is **unauthenticated unless `OPENBOT_API_KEY` is set**: it could create or edit
  bots, post messages as other actors, or answer its own approval questions. Setting
  `OPENBOT_API_KEY` closes that loop only as long as the key is not in the environment the shell
  tool inherits.
- **The `?api_key=` query-string fallback leaks.** Browsers cannot set headers on an SSE
  (`EventSource`) connection, so `/api/v1/events` accepts the key as a query parameter and the
  frontend uses it. Query strings routinely end up in reverse-proxy access logs, browser history
  and `Referer` headers — treat `OPENBOT_API_KEY` as a low-assurance secret, not a real
  credential, and rotate it if such logs are shared.
- **Prompt injection is a live path to all of the above.** A bot that reads a web page, a PR diff,
  or a message from an external actor can be instructed by that content. With `run_shell` enabled
  this is remote code execution. Give each bot the smallest tool set that does its job, use the
  per-tool approval flags for anything destructive, and do not run OpenBot against repositories or
  URLs you do not trust.

Practical guidance: bind to `127.0.0.1`, keep it off shared networks, set `OPENBOT_API_KEY` even
locally, and run it as a dedicated low-privilege user (or in a VM/container) if bots have
`run_shell`. Docker sandboxing for tools is on the roadmap, not in v1.

## Tools and plugins

Bots select from a registry of built-in tools (`run_shell`, `read_file`, `write_file`,
`list_files`, `http_request`, `fetch_url`) plus a handful of
core tools every bot always has (`list_bots`, `start_thread`, `ask_human`, `read_history`,
`recall_messages`, and LangMem's `manage_memory`/`search_memory`).

To add your own tools, drop a Python file with one or more
[`@tool`](https://python.langchain.com/docs/concepts/tools/)-decorated functions into `TOOLS_DIR`
(default `./tools`) — every module-level `BaseTool` in that directory is loaded automatically.
See `tools/example_tools.py`:

```python
from langchain.tools import tool


@tool
def get_time() -> str:
    """Return the current UTC time in ISO-8601 format."""
    ...
```

`GET /api/v1/tools` lists every loaded tool and any load errors.

Only `read_file`, `write_file` and `list_files` are path-confined to the thread working directory,
which defaults to `WORKSPACE_ROOT` and can be set to an existing relative subdirectory when the
thread is created. `run_shell` starts in that directory but is otherwise unrestricted, and
`http_request`/`fetch_url` can reach any URL. Read [Trust model / security](#trust-model--security)
before giving a bot these tools.

## External actors and webhooks

External systems participate as actors. Create one, then exchange mail with it over the REST
API:

```bash
# Register an external actor with a webhook
curl -s -X POST localhost:8000/api/v1/actors \
  -H 'Content-Type: application/json' \
  -d '{"handle": "ci", "name": "CI Bot", "webhook_url": "https://example.com/hook", "webhook_secret": "s3cret"}'

# Send it a message (creates or reuses a 1:1 thread, addressed to the target bot)
curl -s -X POST localhost:8000/api/v1/actors/engineer/messages \
  -H 'Content-Type: application/json' \
  -d '{"content": "The nightly build failed on main.", "from": "ci"}'
```

When mail is queued for an external actor with a `webhook_url`, OpenBot POSTs it there (retrying
after `WEBHOOK_RETRY_DELAYS`, default `5s, 30s, 120s`, then marking the item `failed`). Without a
webhook URL, items just sit `queued` until the external system polls
`GET /api/v1/actors/{handle}/inbox` and acknowledges them.

Webhook request:

- Headers: `X-OpenBot-Kind` (`message` or `question`), `X-OpenBot-Item` (the inbox item id),
  `X-OpenBot-Signature: sha256=<hmac>` (HMAC-SHA256 of the raw body, hex-encoded, using
  `webhook_secret`).
- Body: `{"item_id", "kind", "thread_id", "message", "question", "created_at"}`.

Verify the signature in Python:

```python
import hashlib
import hmac


def verify(secret: str, body: bytes, signature_header: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)
```

## API

Base URL `/api/v1`, JSON throughout, OpenAPI docs at `/docs`. If `OPENBOT_API_KEY` is set, every
route except `/health` requires an `X-API-Key` header.

| Method | Path | Notes |
|---|---|---|
| GET | `/actors` | all actors (kind, handle, name, enabled) |
| POST | `/actors` | create an **external** actor `{handle, name, description?, webhook_url?, webhook_secret?}` |
| GET/PATCH/DELETE | `/actors/{id}` | external actors only for PATCH/DELETE; bots go through `/bots` |
| GET | `/actors/{handle}/inbox?status=queued` | that actor's inbox items |
| POST | `/actors/{handle}/messages` | `{content, from?: handle (default "you"), thread_id?, external_ref?}` — reuses a thread by `external_ref` or `thread_id`, or creates a 1:1 thread; returns `{thread, message, addressed}` |
| GET/POST | `/bots` | list bots; create a bot actor + profile |
| GET/PATCH/DELETE | `/bots/{id}` | delete refuses while runs are open |
| GET/POST | `/threads` | list (latest activity first); create `{title?, handles[], default_bot_handle?, working_directory?}`. `working_directory` must be an existing relative directory under `WORKSPACE_ROOT`; omit it to use `WORKSPACE_ROOT`. |
| GET | `/threads/{id}?before=&limit=` | thread, participants, a page of messages, open runs |
| DELETE | `/threads/{id}` | |
| POST | `/threads/{id}/messages` | `{content, to?: handles[], from?: handle}` → `{message, addressed, unaddressed}` |
| POST | `/threads/{id}/ack` | mark `@you`'s queued message items in the thread done |
| GET | `/inbox?status=queued` | `@you`'s inbox |
| POST | `/inbox/{item_id}/ack` | mark an item done (any actor) |
| GET | `/runs?thread_id=`, `/runs/{id}` | |
| POST | `/runs/{id}/resume` | `{answer}` for a question, or `{decisions: ["approve"\|"reject", ...]}` for an approval |
| POST | `/runs/{id}/cancel` | cancels a queued/running/waiting run |
| GET | `/tools`, `/providers`, `/health` | registry status, configured providers, liveness |
| GET | `/events?thread_id=` | SSE stream: `message.created`, `run.updated`, `run.event`, `inbox.updated` |

## Configuration

All variables live in `.env` at the repo root (also readable from `backend/.env`). Copy
`.env.example` to `.env` and fill in what you need — everything has a sensible default except the
provider keys. Every bot's model defaults to `auto`: it always uses whichever provider is configured
on the server (OpenRouter with the cost-effective `openai/gpt-4o-mini` if `OPENROUTER_API_KEY` is set,
else the first configured provider), so it keeps working as keys are added, removed, or changed. Set
`BOT_MODEL` to any OpenRouter model id to change what "auto" resolves to without editing bot records.
Pick an explicit provider/model per bot in the bot editor (or via the API) to opt out of "auto" for
that bot.

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./openbot.db` | Any SQLAlchemy async URL. `postgresql+asyncpg://...` is supported by the same schema and Alembic migrations, but is untested in v1. |
| `OPENBOT_API_KEY` | *(unset)* | When set, every API route except `/health` requires header `X-API-Key: <value>`. |
| `OPENAI_API_KEY` | *(unset)* | Enables the `openai` provider. |
| `ANTHROPIC_API_KEY` | *(unset)* | Enables the `anthropic` provider. |
| `OPENROUTER_API_KEY` | *(unset)* | Enables the `openrouter` provider. |
| `XAI_API_KEY` | *(unset)* | Enables the `xai` provider (OpenAI-compatible). |
| `BOT_MODEL` | `openai/gpt-4o-mini` | OpenRouter model used for bot LLM calls for seeded bots and any bot whose provider is `openrouter`. Set this in `.env` to switch the whole bot team to a different OpenRouter model; `BOT_MODEL` takes precedence over `OPENROUTER_MODEL`. |
| `OPENROUTER_MODEL` | *(unset)* | Backward-compatible alias for `BOT_MODEL`. |
| `EMBEDDING_MODEL` | `openai:text-embedding-3-small` | Used for semantic memory search; without a matching key, memory search degrades to non-semantic. |
| `EMBEDDING_DIMS` | `1536` | Must match the embedding model's output size. |
| `LANGSMITH_TRACING` | `false` | Enable LangSmith tracing. |
| `LANGSMITH_API_KEY` | *(unset)* | LangSmith API key. |
| `LANGSMITH_PROJECT` | `openbot` | LangSmith project name. |
| `LANGSMITH_ENDPOINT` | *(unset)* | LangSmith endpoint override, for self-hosted/EU instances. |
| `WORKSPACE_ROOT` | `./workspace` | Default thread working directory and the maximum confinement root for file tools. New threads can choose an existing relative subdirectory; `run_shell` only *starts* in the thread directory — it is not sandboxed to it. |
| `TOOLS_DIR` | `./tools` | Directory of plugin tool modules, loaded at startup. |
| `MAX_CONCURRENT_RUNS` | `4` | Global cap on simultaneous bot runs. |
| `MAX_BOT_HOPS` | `20` | Bot-to-bot mention chain limit per thread before a human message is required. |
| `HISTORY_TOKEN_BUDGET` | `24000` | Approximate token budget (chars / 4) for conversation history included in a run. |
| `HISTORY_MAX_MESSAGES` | `80` | Hard cap on the number of history messages included in a run. |
| `MEMORY_REFLECTION_DELAY` | `30` | Seconds to debounce background memory reflection after a run completes. |
| `SEED_DEMO_BOTS` | `true` | Seed `chief_of_staff`, `engineer`, `reviewer`, `qa` on first start if the bot table is empty. |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated list of allowed origins. |
| `WEBHOOK_RETRY_DELAYS` | `5,30,120` | Comma-separated seconds between webhook delivery retries before an item is marked `failed`. |
| `LOG_LEVEL` | `INFO` | Console verbosity (`DEBUG`, `INFO`, `WARNING`, ...). Does not affect the log file, which always records `DEBUG` detail. |
| `LOG_FILE` | `logs/openbot.log` | Rotating diagnostic log (10 MB x 5). See [Troubleshooting](#troubleshooting). |
| `FRONTEND_DIST` | `frontend/dist` | Directory of the built frontend to serve at `/` when it exists. Leave empty in `.env` to use this default; set to a blank value explicitly resolves to the same default, not "disabled". |

## Database

SQLite (`DATABASE_URL=sqlite+aiosqlite:///./openbot.db`) is the default and what the test suite
and demo walkthrough use. All application code goes through SQLAlchemy 2 async and Alembic, with
no SQLite-only SQL, so a `postgresql+asyncpg://...` URL should work as a drop-in replacement —
this path is untested in v1 but is the intended upgrade route. Alembic migrations run
automatically at startup against any non-`:memory:` database; nothing to run by hand.

## Troubleshooting

Every process writes a timestamped diagnostic log to `LOG_FILE` (`logs/openbot.log` by default,
rotating at 10 MB, five backups kept). It always contains `DEBUG` detail regardless of `LOG_LEVEL`,
so it is the place to look when a bot misbehaves:

- `startup: cwd=... workspace_root=... (WORKSPACE_ROOT=...) tools_dir=... database_url=...` -- the
  paths the process actually resolved. Relative settings such as `WORKSPACE_ROOT=./workspace`
  depend on the directory the server was started from; `make dev` and `make run` both start it from
  the repo root, so bots see `<repo>/workspace`, not the repo itself. Clone the project you want
  them to work on into `workspace/` or point `WORKSPACE_ROOT` elsewhere.
- `thread <id> created: ... working_directory=... tool_root=...` -- where a new thread's file and
  shell tools are rooted.
- `run <id> started: bot=@... thread=... working_directory=... tool_root=... model=...` followed
  by one `tool_call` / `tool_result` line per tool invocation (arguments and a preview of the
  result) and a `completed` / `waiting_human` / `failed` line with the elapsed time.
- At `DEBUG`, the full system prompt each run was given.

A bot that reports `frontend does not exist` while listing only a handful of files is almost always
looking at the wrong `tool_root`; the `startup:` and `run ... started:` lines show which one.

## Development

```bash
# backend
cd backend && uv sync
uv run pytest -q
uv run ruff check .
uv run pytest -m smoke -v     # opt-in: live provider calls, costs real money

# frontend
cd frontend && pnpm install
pnpm test
pnpm typecheck
pnpm lint
pnpm build
```

Or, from the repo root: `make test`, `make lint`, `make build`. `make reset_db` deletes the local
SQLite databases (app and LangGraph state); the next start re-runs migrations and re-seeds the demo bots.
The live provider smoke
tests in `backend/tests/smoke/` are marked `smoke` and deselected by default (`addopts =
"-m 'not smoke'"`), so `make test` never bills a provider; run them deliberately with
`make smoke`. Each one skips unless the matching API key is configured.

## Roadmap / out of scope for v1

Accounts and login, multiple human actors, cron triggers, inbound event webhooks (as opposed to
outbound delivery to external actors), MCP servers, Docker sandboxing for tools, chat platform
adapters (Slack/Discord/etc.), and multi-node deployment. The actor system, the LangGraph store,
and the tool registry are designed as the seams for adding these later.

## License

[MIT](LICENSE)
