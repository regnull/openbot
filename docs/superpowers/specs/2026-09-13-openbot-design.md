# OpenBot Design Spec

Date: 2026-09-13 (revised same day for the actor model)
Status: approved
Repo: github.com/regnull/openbot (MIT)

## 1. Purpose

OpenBot is an open-source, self-hosted implementation of the "Grok Bot" idea: a web app that hosts
multiple persistent AI bots. Each bot has a name, a description, and instructions that govern its
behavior. Bots talk to humans and to each other in shared threads, use pluggable tools, keep
long-term memory, and can be reached by external systems over HTTP. Chains of bots form
workflows, for example: Chief of Staff delegates to Engineer, Engineer opens a PR, Reviewer reviews
it, QA tests it and asks a human for approval, then merges.

## 2. Decisions already made

| Topic | Decision |
|---|---|
| Model | **Actor model.** Every participant (bot, human, external system) is an actor with a persistent inbox. Actors post messages into each other's inboxes through shared threads. |
| Stack | Python backend (FastAPI, LangChain 1.x + LangGraph, SQLAlchemy 2 async, Alembic). TypeScript frontend (React 19, Vite, Tailwind, TanStack Query). |
| Database | Standard SQL through SQLAlchemy. SQLite in v1 via `DATABASE_URL`. Postgres/MySQL later by changing the URL; no SQLite-only SQL in application code. |
| Providers | OpenAI, Anthropic, OpenRouter required. xAI included because it is OpenAI-compatible. Keys from environment. |
| Auth | Single operator. No login. One built-in human actor `@you`. Optional static `OPENBOT_API_KEY` protects the whole API when set. |
| External I/O | External systems are actors: they post through the REST API and receive their inbox by signed webhook POST or by polling. SSE stream for the UI. |
| Tools | Python plugin directory of `@tool` functions plus built-ins. No MCP in v1. |
| Shell | Built-in shell/file tools execute on the host inside `WORKSPACE_ROOT`. No sandbox in v1. |
| Triggers | Inbox mail only. No cron, no inbound event webhooks in v1. |
| Memory | LangMem on the LangGraph store. Persistent per-bot memory. Recent messages in context, older messages recallable. No context purge. |
| Concurrency | One run at a time per bot actor (classic actor). Global cap on concurrent runs. |
| Approvals | `ask_human` tool and per-tool approval flags using LangGraph interrupts; answers arrive as `resume` mail. |
| Demo | First run seeds Chief of Staff, Engineer, Reviewer, QA bots. |
| Packaging | `make dev` with uv and pnpm. No Docker in v1. |
| Tracing | LangSmith via standard env vars. |

## 3. Architecture

Single backend process. FastAPI serves the REST API, the SSE event stream, and (in production)
the built frontend. An in-process **actor system** owns one worker per bot actor (drains its inbox
and runs the agent) and one worker per external actor (delivers its inbox by webhook). Humans have
no worker; the UI reads their inbox.

```
Browser (as @you) / external systems (as external actors)
        |  HTTP (REST, SSE)
        v
+------------------------------ FastAPI --------------------------------+
| api/       routers: actors, bots, threads, messages, inbox, runs,      |
|            tools, providers, events                                    |
| runtime/   delivery  -> post a message: create row, resolve targets,   |
|                         write inbox items, publish events, wake actors |
|            actors    -> ActorSystem: BotActor and ExternalActor workers|
|            runner    -> executes one bot run with a LangChain agent    |
|            prompt    -> system prompt + history from the bot's view    |
|            memory    -> LangMem tools, message index, reflection       |
|            providers -> chat model + embedding factories               |
|            bus       -> in-process pub/sub feeding SSE                 |
| tools/     registry + builtin tools + plugin loader                    |
| db/        SQLAlchemy models, session, Alembic migrations              |
+------------------------------------------------------------------------+
        |                              |
        v                              v
   SQL database                  LLM providers, LangSmith
   (app tables + LangGraph
    checkpointer + store)
```

### Repo layout

```
openbot/
  backend/
    pyproject.toml            uv-managed, Python 3.12+
    openbot/
      main.py                 app factory, lifespan
      config.py               Settings (pydantic-settings) from env / .env
      services.py             Services container
      db/  models.py session.py migrations/
      api/ deps.py schemas.py actors.py bots.py threads.py messages.py inbox.py runs.py tools.py providers.py events.py
      runtime/ router.py delivery.py actors.py runner.py prompt.py memory.py providers.py persistence.py bus.py
      tools/ context.py registry.py builtin/{workspace,shell,files,http,core}.py
      seed.py
    tests/
  frontend/  React 19 + Vite + TypeScript + Tailwind + TanStack Query
  tools/     user plugin dir (example_tools.py ships)
  docs/superpowers/{specs,plans}/
  Makefile README.md LICENSE .env.example .github/workflows/ci.yml
```

## 4. Data model

All ids are UUID strings. Timestamps are UTC. JSON columns use SQLAlchemy `JSON` (portable).

**actors**: id, kind (`bot|human|external`), handle (unique, `[a-z0-9_-]{2,32}`), name, description,
enabled, created_at, updated_at.

**bot_profiles** (1:1 with a bot actor): actor_id (PK, FK), instructions, provider
(`openai|anthropic|openrouter|xai`), model, model_settings JSON (`temperature`, `max_tokens`),
tool_names JSON, approval_tools JSON (subset of tool_names), memory_enabled bool.

**external_profiles** (1:1 with an external actor): actor_id (PK, FK), webhook_url nullable,
webhook_secret nullable.

**threads**: id, title, created_by_actor_id nullable, external_ref nullable (unique when set),
hop_limit_notified bool, last_message_at, created_at, updated_at.

**thread_participants**: id, thread_id, actor_id; unique (thread_id, actor_id).

**messages**: id, thread_id, sender_actor_id nullable (null for system), sender_kind
(`bot|human|external|system`), sender_name, content, mentions JSON (actor ids), hop int
(0 for human/external/system), run_id nullable, metadata JSON, created_at. Index (thread_id, created_at).

**inbox_items**: id, actor_id, thread_id nullable, kind (`message|question|resume`), message_id
nullable, run_id nullable, payload JSON, status (`queued|processing|done|cancelled|failed`),
attempts int, last_error nullable, created_at, processed_at nullable. Index (actor_id, status, created_at).
- `message`: a thread message the actor should act on (bot) or be notified of (human/external).
- `question`: a bot's run is waiting for human input (payload = the run's interrupt, plus run_id).
- `resume`: an answer or approval decision for a parked run of this bot (payload = resume value).

**runs**: id, actor_id (bot), thread_id, status (`queued|running|waiting_human|completed|failed|cancelled`),
interrupt JSON nullable, error nullable, langsmith_run_id nullable, created_at, started_at, finished_at.
The inbox items that triggered a run carry its id in `run_id`.

**run_events**: id, run_id, seq, type (`text|tool_call|tool_result|interrupt|resumed|error|message`),
payload JSON, created_at; unique (run_id, seq).

LangGraph owns the checkpointer (parked run state) and store (memories, message index) tables in
the same database: `AsyncSqliteSaver`/`AsyncSqliteStore` for SQLite (in `<db>.langgraph.db`),
Postgres equivalents for `postgresql://`. Application tables are the source of truth for threads
and messages. Checkpointer thread_id = run id.

## 5. Delivery and routing

`delivery.post_message(thread, sender, content, to)`:

1. **Bot targets** are resolved by `router.resolve_targets`: bots named in `to` plus bots mentioned
   as `@handle`, in order, deduplicated; if none and the thread has exactly one bot participant,
   that bot; the sender is removed (a bot never triggers itself); disabled actors are removed;
   a system message (sender null) never targets anyone.
2. The message row is created. Target bots that are not participants are added.
3. **Hop guard**: `hop` = 0 for human/external/system messages, `trigger hop + 1` for bot messages.
   If targets exist and `hop >= MAX_BOT_HOPS` (default 20), no bot items are created; a system
   notice "Bot-to-bot hop limit reached; a human message resets it" is posted once per thread
   until a hop-0 message arrives (`threads.hop_limit_notified`).
4. **Inbox items**: one `message` item per target bot; one `message` item per human or external
   participant other than the sender (notification). Items start `queued`.
5. Events `message.created`, `inbox.updated` are published; the message is indexed into the store;
   the actor system is woken for each actor that received an item.

**Bot actor worker** (one per bot, sequential):
- Picks the oldest `queued` item, skipping `message` items whose thread has a `waiting_human` run
  of this bot (that thread waits for the answer). A `resume` item is processed alone. A `message`
  item is batched with every other queued `message` item in the same thread.
- For a message batch it creates a run (`queued`) and links the items, marks them `processing`,
  and calls the runner. For a resume item it calls the runner with the resume command.
- On completion the items become `done`; on cancellation `cancelled`; on run failure `done`
  (the failure is visible as a system message).
- A global semaphore (`MAX_CONCURRENT_RUNS`, default 4) caps runs across all bots.

**External actor worker** (one per external actor with a webhook URL): delivers `queued`
`message` and `question` items in order by POST, retrying after `WEBHOOK_RETRY_DELAYS` (5s, 30s,
120s), then marks `failed`. Without a webhook URL items stay `queued` until acknowledged via the
API. Body: `{item_id, kind, thread_id, message|null, question|null, created_at}`; headers
`X-OpenBot-Kind`, `X-OpenBot-Item`, `X-OpenBot-Signature: sha256=<hmac(secret, body)>`.

**Human actor**: `@you` has no worker. Its `message` items are acknowledged when the UI opens the
thread (`POST /threads/{id}/ack`); `question` items are acknowledged by resuming the run.

**Bot replies**: the run's final assistant text is posted as a bot message (hop rule applies) and
delivered like any other message, so `@mention` hand-offs wake the next bot.

**Side threads**: `start_thread(title, handles, message)` creates a thread with the calling bot and
the named actors, posts the first message from the bot with the current hop.

## 6. Bot runtime

`runner.execute(run_id, resume=None)`:

1. Load run, bot actor (+profile), thread, trigger messages (messages of items linked to the run).
   Set `running`, emit `run.updated`.
2. Tools: registry lookup for `tool_names` + always-on core tools (`list_bots`, `start_thread`,
   `ask_human`, `read_history`, `recall_messages`) + LangMem `manage_memory`/`search_memory`.
   `RunContext(actor_id, handle, name, thread_id, run_id, workspace_root, services, hop)` is passed as
   LangGraph runtime context.
3. System prompt (`prompt.build_system_prompt`): identity, instructions verbatim, roster of enabled
   bots with handles and descriptions and the mention rule, thread participants, top-8 relevant
   memories (query = trigger text), tool guidance, workspace root, note about older messages.
4. History (`prompt.build_history`): newest messages first until `HISTORY_TOKEN_BUDGET` (24k,
   chars/4) or `HISTORY_MAX_MESSAGES` (80), reversed. Own messages → `AIMessage`; everything else →
   `HumanMessage("[name]: text")`, consecutive ones merged.
5. `create_agent(model, tools, system_prompt, middleware=[HumanInTheLoopMiddleware(interrupt_on=approval_tools)], checkpointer, store, context_schema=RunContext)`.
6. Stream `stream_mode=["messages","updates"]` with `configurable.thread_id = run.id`. Persist
   `run_events` for tool calls, tool results, text, interrupts; publish token deltas transiently.
7. Interrupt → normalize to `{"kind":"question","question"}` or `{"kind":"approval","actions":[{name,args}]}`,
   store on the run, set `waiting_human`, create `question` inbox items for human and external
   participants, return.
8. Completion → post the bot message, set `completed`, schedule memory reflection.
9. Exception → `failed` with a one-line error, system message `"@handle failed: {error}"`.
10. Cancellation → `cancelled`, system message.

Providers, embeddings, tracing: unchanged from the original spec (`openai`, `anthropic`,
`openrouter`, `xai` via `ChatOpenAI`/`ChatAnthropic`; `EMBEDDING_MODEL` default
`openai:text-embedding-3-small`, degrade to non-semantic search without a key; LangSmith env
passthrough with the root run id stored on the run).

## 7. Approvals and human input

`POST /api/v1/runs/{id}/resume` with `{"answer": str}` (question) or `{"decisions": ["approve"|"reject", ...]}`
(approval) validates the run is `waiting_human` and the body matches `interrupt.kind`, marks the
human's `question` item done, and enqueues a `resume` item in the bot's inbox with payload
`{"resume": <value>}`. The bot worker resumes the run with `Command(resume=value)`.
`POST /runs/{id}/cancel` cancels queued/running/waiting runs. On restart: `running` runs become
`failed` ("server restarted") and their items `done`; `processing` items become `queued`;
`waiting_human` runs are kept (state is in the checkpointer).

## 8. Memory (LangMem)

Unchanged: LangGraph store with semantic index; bot namespace `("bots", actor_id, "memories")` with
LangMem `manage_memory`/`search_memory` tools and prompt injection of relevant memories; background
reflection after each completed run via `create_memory_store_manager` with a per-bot debounce of
`MEMORY_REFLECTION_DELAY` seconds; thread namespace `("threads", thread_id, "messages")` holds every
message for `recall_messages`; `read_history` pages the SQL table. Nothing is ever purged.

## 9. Tools

Unchanged: registry loads built-ins then every `BaseTool` in `TOOLS_DIR/*.py`; `GET /tools` lists
tools and load errors. Selectable built-ins `run_shell`, `read_file`, `write_file`, `list_files`,
`http_request`, `fetch_url` (all confined to `WORKSPACE_ROOT`, outputs capped). Core tools always
attached. Example plugin ships.

## 10. External API

Base `/api/v1`, JSON, OpenAPI at `/docs`. `X-API-Key` required when `OPENBOT_API_KEY` is set.

| Method | Path | Notes |
|---|---|---|
| GET | `/actors` | all actors (kind, handle, name, enabled) |
| POST | `/actors` | create an **external** actor `{handle, name, description?, webhook_url?, webhook_secret?}` |
| GET/PATCH/DELETE | `/actors/{id}` | external actors only for PATCH/DELETE; bots via `/bots` |
| GET | `/actors/{handle}/inbox?status=queued` | that actor's inbox items |
| POST | `/actors/{handle}/messages` | `{content, from?: handle (default "you"), thread_id?, external_ref?}`; with `thread_id` posts there addressed to the actor; otherwise reuses the thread with `external_ref` or creates a 1:1 thread; returns `{thread, message, runs}` |
| GET/POST | `/bots` | list; create bot actor + profile (flattened fields) |
| GET/PATCH/DELETE | `/bots/{id}` | delete refuses while runs are open |
| GET/POST | `/threads` | list (latest activity first); create `{title?, handles[]}` |
| GET | `/threads/{id}?before=&limit=` | thread, participants, messages page, open runs |
| DELETE | `/threads/{id}` | |
| POST | `/threads/{id}/messages` | `{content, to?: handles[], from?: handle}` → `{message, runs, unaddressed}` |
| POST | `/threads/{id}/ack` | mark `@you`'s queued message items in the thread done |
| GET | `/inbox?status=queued` | `@you`'s inbox |
| POST | `/inbox/{item_id}/ack` | mark an item done (any actor) |
| GET | `/runs?thread_id=`, `/runs/{id}` | |
| POST | `/runs/{id}/resume`, `/runs/{id}/cancel` | |
| GET | `/tools`, `/providers`, `/health` | |
| GET | `/events?thread_id=` | SSE: `message.created`, `run.updated`, `run.event`, `inbox.updated` |

## 11. Frontend

Left navigation: Inbox, Threads, Bots, Settings.

- **Inbox**: `@you`'s queued items: pending questions (answer/approve/reject inline) and unread
  messages grouped by thread; click opens the thread and acknowledges.
- **Threads** and **Thread view**: as before (messages with avatars, collapsible tool-call cards
  from run events, streaming text, run status strip, inline question/approval card, `@handle`
  autocomplete composer, LangSmith link). Opening a thread acknowledges it.
- **Bots**: cards and editor (name, handle, description, instructions, provider, model, tool
  checklist with per-tool approval toggle, memory switch, enabled switch).
- **Settings**: provider status, embedding status, workspace root, tool registry with load errors,
  API key entry, external actors list/create/delete (with webhook URL).

## 12. Configuration

```
DATABASE_URL=sqlite+aiosqlite:///./openbot.db
OPENBOT_API_KEY=
OPENAI_API_KEY= ANTHROPIC_API_KEY= OPENROUTER_API_KEY= XAI_API_KEY=
EMBEDDING_MODEL=openai:text-embedding-3-small
EMBEDDING_DIMS=1536
LANGSMITH_TRACING=true LANGSMITH_API_KEY= LANGSMITH_PROJECT=openbot LANGSMITH_ENDPOINT=
WORKSPACE_ROOT=./workspace
TOOLS_DIR=./tools
MAX_CONCURRENT_RUNS=4
MAX_BOT_HOPS=20
HISTORY_TOKEN_BUDGET=24000
HISTORY_MAX_MESSAGES=80
MEMORY_REFLECTION_DELAY=30
WEBHOOK_RETRY_DELAYS=5,30,120
SEED_DEMO_BOTS=true
CORS_ORIGINS=http://localhost:5173
FRONTEND_DIST=
```

## 13. Seeded actors

At every start: the human actor `@you` ("You") exists. On first start with an empty bot table
and a configured provider: **chief_of_staff**, **engineer**, **reviewer**, **qa** with the
instructions from the original spec (coordinator delegates by mention; engineer implements and
opens PRs then mentions reviewer; reviewer reviews with `gh` and mentions engineer or qa; qa runs
tests, asks the human before merging, merges). Default provider is the first configured in the
order openai, anthropic, openrouter, xai.

README walkthrough: clone a repo into `workspace/`, start OpenBot, open a thread with
`@chief_of_staff`, ask for a change, watch delegation, approve the merge from the Inbox.

## 14. Testing

Backend pytest with in-memory SQLite, `InMemoryStore`/`InMemorySaver`, and a scripted fake chat
model: routing, hop limit, delivery to inboxes, bot worker ordering/batching/parking, runner
(tools, question, approval, failure, hand-off), external delivery with retries and signatures,
inbox and ack APIs, SSE. Provider smoke tests skipped without keys. Frontend `tsc`, vitest for the
mention parser and event reducer, `vite build`. GitHub Actions CI.

## 15. Out of scope for v1

Accounts and login, multiple human actors, cron triggers, inbound event webhooks, MCP servers,
Docker sandboxing, chat platform adapters, multi-node deployment. The actor system, store, and
tool registry are the seams for these.
