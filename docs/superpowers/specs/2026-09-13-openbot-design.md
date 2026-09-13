# OpenBot Design Spec

Date: 2026-09-13
Status: approved design, pending spec review
Repo: github.com/regnull/openbot (MIT)

## 1. Purpose

OpenBot is an open-source, self-hosted implementation of the "Grok Bot" idea: a web app that hosts
multiple persistent AI bots. Each bot has a name, a description, and instructions that govern its
behavior. Bots talk to humans and to each other in shared threads, use pluggable tools, keep
long-term memory, and can be reached by external systems over HTTP. Chains of bots form
workflows, for example: Engineer opens a PR, Reviewer reviews it, QA tests it and asks a human
for approval, then merges.

## 2. Decisions already made

| Topic | Decision |
|---|---|
| Stack | Python backend (FastAPI, LangChain 1.x + LangGraph, SQLAlchemy 2 async, Alembic). TypeScript frontend (React 19, Vite, Tailwind, TanStack Query). |
| Database | Standard SQL through SQLAlchemy. SQLite in v1 via `DATABASE_URL`. Postgres/MySQL later by changing the URL; no SQLite-only SQL in application code. |
| Providers | OpenAI, Anthropic, OpenRouter required. xAI included because it is OpenAI-compatible. Keys from environment. |
| Auth | Single operator. No login. Optional static `OPENBOT_API_KEY` protects the whole API when set. |
| External I/O | REST API + outbound webhooks + SSE. No chat platform adapters in v1. |
| Tools | Python plugin directory of `@tool` functions plus built-ins. No MCP in v1. |
| Shell | Built-in shell/file tools execute on the host inside `WORKSPACE_ROOT`. No sandbox in v1. |
| Triggers | Messages only. No cron, no inbound webhooks in v1. |
| Memory | LangMem on the LangGraph store. Persistent per-bot memory. Recent messages in context, older messages recallable. No context purge. |
| Messaging | Shared threads with participants; `@handle` mentions route work between bots. |
| Approvals | `ask_human` tool and per-tool approval flags using LangGraph interrupts. |
| Demo | First run seeds Engineer, Reviewer, QA bots. |
| Packaging | `make dev` with uv and pnpm. No Docker in v1. |
| Tracing | LangSmith via standard env vars. |

## 3. Architecture

Single backend process. FastAPI serves the REST API, the SSE event stream, and (in production)
the built frontend. An in-process asyncio run worker executes bot runs. The run queue is an
interface (`RunQueue`) with one implementation (`InProcessRunQueue`) so a separate worker can
be added later without touching the API layer.

```
Browser / external client
        |  HTTP (REST, SSE)
        v
+------------------------------ FastAPI ------------------------------+
| api/       routers: bots, threads, messages, runs, tools, webhooks,  |
|            events                                                    |
| runtime/   router  -> decides which bots run for a message           |
|            queue   -> InProcessRunQueue (asyncio), concurrency caps  |
|            runner  -> executes one run with a LangChain agent        |
|            prompt  -> builds system prompt + history for a bot       |
|            memory  -> LangMem tools, store, reflection               |
|            providers -> chat model + embedding factories             |
|            bus     -> in-process pub/sub feeding SSE and webhooks    |
| tools/     registry + builtin tools + plugin loader                  |
| db/        SQLAlchemy models, session, Alembic migrations            |
+----------------------------------------------------------------------+
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
      main.py                 app factory, lifespan (db, store, queue, seed)
      config.py               Settings (pydantic-settings) from env / .env
      db/
        models.py             SQLAlchemy models
        session.py            engine + session factory
        migrations/           Alembic
      api/
        deps.py               session, auth dependency
        bots.py threads.py messages.py runs.py tools.py webhooks.py events.py
        schemas.py            Pydantic request/response models
      runtime/
        router.py queue.py runner.py prompt.py memory.py providers.py bus.py webhooks.py
      tools/
        registry.py           discovery, lookup, ToolSpec
        context.py            RunContext passed to tools
        builtin/              shell.py files.py http.py messaging.py human.py
      seed.py
    tests/
  frontend/
    package.json vite.config.ts tsconfig.json
    src/
      api/                    typed client + SSE hook
      pages/                  Bots, BotEditor, Threads, ThreadView, Settings
      components/
      lib/                    mentions parser, event reducer
  tools/                      user plugin dir (example_tools.py ships)
  docs/superpowers/specs/
  Makefile README.md LICENSE .env.example .github/workflows/ci.yml
```

## 4. Data model

All ids are UUID strings. Timestamps are UTC. JSON columns use SQLAlchemy `JSON` (portable).

**bots**
- id, handle (unique, `[a-z0-9_-]{2,32}`, used in `@handle`), name, description, instructions
- provider (`openai|anthropic|openrouter|xai`), model (string), model_settings JSON (`temperature`, `max_tokens`, optional)
- tool_names JSON list, approval_tools JSON list (subset of tool_names that pause for approval)
- memory_enabled bool (default true): background memory extraction after runs
- enabled bool, created_at, updated_at

**threads**
- id, title, created_by_kind (`human|external|bot`), created_by_bot_id nullable, external_ref nullable (unique when set), created_at, updated_at

**thread_participants**
- id, thread_id, kind (`bot|human|external`), bot_id nullable, unique (thread_id, kind, bot_id)

**messages**
- id, thread_id, sender_kind (`human|bot|external|system`), sender_bot_id nullable, sender_name
- content text, mentions JSON list of bot ids, hop int (0 for human/external/system)
- run_id nullable (the run that produced a bot message), metadata JSON, created_at
- index (thread_id, created_at)

**runs**
- id, bot_id, thread_id, trigger_message_id
- status (`queued|running|waiting_human|completed|failed|cancelled`)
- interrupt JSON nullable (pending question or tool approval request, see 7)
- error text nullable, langsmith_run_id nullable, created_at, started_at, finished_at

**run_events**
- id, run_id, seq int, type (`text|tool_call|tool_result|interrupt|resumed|error|message`), payload JSON, created_at
- unique (run_id, seq)

**webhooks**
- id, url, secret, events JSON list, thread_id nullable, bot_id nullable, enabled, created_at

**webhook_deliveries**
- id, webhook_id, event, payload JSON, status (`pending|delivered|failed`), attempts, last_error, created_at, delivered_at

LangGraph owns two more sets of tables in the same database: the checkpointer (run state for
interrupts) and the store (memories and message index). SQLite uses `AsyncSqliteSaver` and
`AsyncSqliteStore` from `langgraph-checkpoint-sqlite`; Postgres uses the `langgraph-checkpoint-postgres`
equivalents. Selection is by `DATABASE_URL` scheme. Application tables, not the checkpointer,
are the source of truth for threads and messages. Checkpointer thread_id = run id, so each run
has isolated graph state.

## 5. Messaging and routing

**Posting.** A message is created by a human (UI), an external caller (API), or a bot (runner).
Targets are resolved by `router.resolve_targets(thread, message)`:

1. Bots named in `to` (API field) plus bots mentioned as `@handle` in the content, deduplicated.
2. If that set is empty and the thread has exactly one bot participant, that bot.
3. Otherwise no targets. The API response and UI show "no bot addressed".
4. The sending bot is removed from the set (a bot never triggers itself). Disabled bots are removed.

Bots that are targeted but not yet participants are added as participants.

**Runs.** One run is created per target. Constraints:
- One active (`queued|running|waiting_human`) run per (bot, thread). A message targeting a bot
  that already has an active run in that thread is recorded with `metadata.pending_for=[bot_id]`;
  when the active run finishes, the runner checks for pending messages and starts one follow-up run
  whose trigger is the latest pending message. The bot sees all of them in history.
- Global cap `MAX_CONCURRENT_RUNS` (default 4) enforced by the queue semaphore.

**Hop limit.** `hop` = 0 for human/external/system messages; a bot message gets
`trigger_message.hop + 1`. If a target would be triggered by a message with `hop >= MAX_BOT_HOPS`
(default 20), no run is created and a system message "Bot-to-bot hop limit reached; a human
message resets it" is posted once per thread until a hop-0 message arrives.

**Bot replies.** The final assistant text of a run becomes one bot message in the thread. Mentions
in it are routed as above. If the final text is empty (the bot only used tools), a system event
is recorded but no message is posted.

**Side threads.** The `start_thread` tool creates a new thread with the calling bot and the named
bots/human as participants and posts the first message from the calling bot; routing applies.

## 6. Bot runtime

`runner.execute(run_id)`:

1. Load bot, thread, trigger message. Mark run `running`, emit `run.updated`.
2. Build tools: registry lookup for `bot.tool_names` plus always-on tools (`list_bots`,
   `start_thread`, `ask_human`, `manage_memory`, `search_memory`, `recall_messages`,
   `read_history`). Bind `RunContext(bot, thread, run)` via LangGraph runtime context.
3. Build system prompt (`prompt.build_system_prompt`):
   - identity: name, handle, description
   - the bot's instructions verbatim
   - roster: every enabled bot's handle and description, with the rule "to hand off, mention
     `@handle` in your reply"
   - thread participants
   - top-K (default 8) memories from the bot's namespace relevant to the trigger message
   - tool guidance: mentions, `ask_human`, approvals, memory tools, history recall, workspace root
4. Build history (`prompt.build_history`): the thread's messages newest-first until the token
   budget `HISTORY_TOKEN_BUDGET` (default 24k, estimated by chars/4) or `HISTORY_MAX_MESSAGES`
   (default 80) is hit, then reversed. The bot's own messages become `AIMessage`; all other
   messages become `HumanMessage` with content `"[{sender_name}]: {content}"`. System messages
   are included the same way with sender `system`. A leading note tells the bot how many older
   messages exist and that `recall_messages` / `read_history` can fetch them.
5. `create_agent(model, tools, system_prompt, middleware=[HumanInTheLoopMiddleware(interrupt_on=approval_tools)], checkpointer, store)`.
6. Stream with `stream_mode=["messages","updates"]`, `config={"configurable": {"thread_id": run.id}}`
   and LangSmith metadata (`bot`, `thread_id`, `run_id`). Persist `run_events` for text chunks
   (batched per message), tool calls, tool results, interrupts. Publish to the bus.
7. On interrupt: store the interrupt payload on the run, set `waiting_human`, emit
   `run.waiting_human`, return. Resume (section 7) re-enters step 6 with `Command(resume=...)`.
8. On completion: post the bot message (hop rule), set `completed`, emit `run.completed`,
   schedule memory reflection (section 8), check pending messages.
9. On exception: set `failed` with a one-line error, post a system message
   `"@handle failed: {error}"` (no hop increment, never routed), emit `run.failed`.

**Providers** (`providers.chat_model(bot)`): `openai` → `ChatOpenAI`; `anthropic` → `ChatAnthropic`;
`openrouter` → `ChatOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)`;
`xai` → `ChatOpenAI(base_url="https://api.x.ai/v1", api_key=XAI_API_KEY)`. `GET /providers` lists
providers with `configured: bool` and a curated model list; the UI also accepts any model id.

**Embeddings** (`providers.embeddings()`): `EMBEDDING_MODEL` (default `openai:text-embedding-3-small`).
If no embedding provider key is configured, the store runs without a semantic index and memory /
recall tools fall back to the store's non-semantic filtered listing (most recent first).

**Tracing**: `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT`
are passed through. The runner captures the root run id via a `RunCollectorCallbackHandler` and
stores it on the run; the UI links to `https://smith.langchain.com/...` when present.

## 7. Approvals and human input

Two mechanisms, one resume endpoint.

- **`ask_human(question: str)`** built-in tool calls `langgraph.types.interrupt({"kind": "question", "question": ...})`.
- **Tool approval**: tools in `bot.approval_tools` are wrapped by `HumanInTheLoopMiddleware` with
  `allowed_decisions=["approve","reject"]`. The interrupt payload contains `action_requests`.

The runner normalizes both into `run.interrupt`:

```json
{"kind": "question", "question": "Merge PR #12?"}
{"kind": "approval", "actions": [{"name": "run_shell", "args": {"command": "gh pr merge 12"}}]}
```

`POST /api/v1/runs/{id}/resume` body: `{"answer": "yes"}` for questions, or
`{"decisions": ["approve"|"reject", ...]}` for approvals (one per action). The endpoint validates
the run is `waiting_human`, records a `resumed` run event, and re-queues the run with the resume
command. Waiting runs survive restarts because state lives in the checkpointer; on startup, runs
in `running` are marked `failed` ("server restarted"), runs in `waiting_human` are left as is.

`POST /api/v1/runs/{id}/cancel` cancels queued/running/waiting runs (asyncio task cancellation;
status `cancelled`, system message posted).

## 8. Memory (LangMem)

Store: LangGraph `BaseStore` with semantic index `{"embed": embeddings, "dims": N}`.

**Bot long-term memory.** Namespace `("bots", bot.id, "memories")`.
- Tools: `create_manage_memory_tool(namespace)` and `create_search_memory_tool(namespace)` from
  LangMem, always attached.
- Prompt injection: at run start, `store.asearch(namespace, query=trigger.content, limit=8)`;
  results are listed in the system prompt under "Your memories".
- Background reflection: when `bot.memory_enabled`, after each completed run the runner submits
  the run's message trajectory to a `ReflectionExecutor` wrapping
  `create_memory_store_manager(REFLECTION_MODEL, namespace=..., enable_inserts=True, enable_deletes=False)`
  with a debounce of `MEMORY_REFLECTION_DELAY` seconds (default 30) keyed by bot id. The
  reflection model defaults to the bot's own model. Failures are logged, never surfaced to the
  thread.

**Thread history recall (no purge).** Every message (any sender) is written to the store at
namespace `("threads", thread.id, "messages")` with key = message id and value
`{"sender": name, "content": text, "created_at": ts, "message_id": id}`, indexed on `content`.
- `recall_messages(query: str, limit: int = 10)`: semantic search in the current thread's
  namespace; returns sender, time, content.
- `read_history(before_message_id: str | None, limit: int = 20)`: chronological page of messages
  from the SQL table, oldest first within the page, so the bot can walk back through the thread.
- The full message table is never trimmed, summarized, or deleted by the runtime.

## 9. Tools

**Registry.** `ToolSpec(name, description, tool, source)` where `source` is `builtin` or the
plugin file path. On startup the registry loads built-ins, then imports every `*.py` under
`TOOLS_DIR` (default `./tools`) and collects every `BaseTool` instance found at module level
(including functions decorated with `@tool`). Import errors are logged and skipped; the tool
list endpoint reports them. Name collisions: the later one wins with a warning.

**Run context.** Tools receive `RunContext` via `ToolRuntime` (LangChain 1.x
`runtime.context`), giving `bot_id`, `bot_handle`, `thread_id`, `run_id`, `workspace_root`, and a
`services` handle (session factory, store, bus, router) so built-ins and plugins can post
messages, start threads, or read history.

**Built-ins (selectable per bot):**
- `run_shell(command, cwd=None, timeout=120)`: `bash -lc` inside `WORKSPACE_ROOT` (cwd must
  resolve within it). Captures stdout/stderr, exit code; output capped at 20k chars with a note.
  This is how bots use git and gh.
- `read_file(path)`, `write_file(path, content)`, `list_files(path=".", depth=2)`: paths resolved
  inside `WORKSPACE_ROOT`; escapes are refused.
- `http_request(method, url, headers=None, body=None)`: returns status, headers, body (capped).
- `fetch_url(url)`: GET and convert HTML to readable text (capped).

**Always attached:** `list_bots`, `start_thread(title, handles, message)`, `ask_human`,
`manage_memory`, `search_memory`, `recall_messages`, `read_history`.

**Example plugin** `tools/example_tools.py` ships with `get_time()` and `word_count(text)` to
show the pattern.

## 10. External API

Base `/api/v1`, JSON, FastAPI OpenAPI docs at `/docs`. If `OPENBOT_API_KEY` is set, every request
under `/api` must send `X-API-Key`; otherwise the API is open (intended for localhost). CORS
allows the Vite dev origin in dev.

| Method | Path | Notes |
|---|---|---|
| GET/POST | `/bots` | list, create |
| GET/PATCH/DELETE | `/bots/{id}` | delete refuses if the bot has active runs |
| POST | `/bots/{handle}/messages` | body `{content, sender_name?, external_ref?}`; reuses the thread with that `external_ref` or creates a 1:1 thread; returns `{thread, message, runs}` |
| GET/POST | `/threads` | list (newest activity first), create `{title?, handles[]}` |
| GET | `/threads/{id}` | thread + participants + messages (paginated, `before`, `limit`) + active runs |
| POST | `/threads/{id}/messages` | body `{content, to?: handles[], sender_kind?: human/external, sender_name?}`; returns `{message, runs}` |
| GET | `/runs?thread_id=` | list |
| GET | `/runs/{id}` | run + events |
| POST | `/runs/{id}/resume` | see section 7 |
| POST | `/runs/{id}/cancel` | |
| GET | `/tools` | registry contents and load errors |
| GET | `/providers` | providers, configured flags, curated models |
| GET/POST | `/webhooks`, DELETE `/webhooks/{id}` | |
| GET | `/events?thread_id=` | SSE; omit `thread_id` for all events |
| GET | `/health` | |

**SSE events** (`event:` name, `data:` JSON): `message.created`, `run.updated` (status change,
includes `interrupt` when waiting), `run.event` (a run_event row). The bus is in-process; each SSE
client subscribes to a queue with a 1000-item cap (drops oldest with a warning event).

**Webhooks.** Subscribable events: `message.created` (bot messages only), `run.waiting_human`,
`run.completed`, `run.failed`. Optional filters by thread or bot. Delivery: POST JSON with headers
`X-OpenBot-Event`, `X-OpenBot-Delivery`, `X-OpenBot-Signature: sha256=<hmac(secret, body)>`.
Retries at 5s, 30s, 120s, then `failed`. Deliveries are recorded in `webhook_deliveries`.

## 11. Frontend

Left navigation with Bots, Threads, Settings. Dark/light follows the system.

- **Bots**: grid of bot cards (name, handle, model, tool count, enabled). "New bot" and card click
  open the editor: name, handle, description, instructions (textarea), provider select, model
  combobox (curated + free text), tool checklist with a "requires approval" toggle per checked
  tool, memory enabled switch, enabled switch, save/delete.
- **Threads**: list sorted by last activity with participant avatars and last message preview.
  "New thread" picks bots. Thread view: message list grouped by sender with colored avatar
  initials; bot messages show collapsible tool-call cards (name, args, result, duration) from
  run events; streaming text appears as it arrives; a run status strip shows active/waiting runs;
  when a run is `waiting_human`, an inline card shows the question or the pending action with
  Answer / Approve / Reject; the composer supports `@handle` autocomplete and Enter-to-send. A
  "LangSmith" link appears on bot messages whose run has a trace id.
- **Settings**: provider configured status, embedding model, workspace root, tool registry with
  load errors, API key entry (stored in localStorage) when the server requires one, webhook list
  with create/delete.

State: TanStack Query for REST, one SSE connection per open thread feeding a reducer that
patches the query cache (messages, runs, run events).

## 12. Configuration

`.env` (see `.env.example`), read by pydantic-settings:

```
DATABASE_URL=sqlite+aiosqlite:///./openbot.db
OPENBOT_API_KEY=            # optional
OPENAI_API_KEY= ANTHROPIC_API_KEY= OPENROUTER_API_KEY= XAI_API_KEY=
EMBEDDING_MODEL=openai:text-embedding-3-small
LANGSMITH_TRACING=true LANGSMITH_API_KEY= LANGSMITH_PROJECT=openbot LANGSMITH_ENDPOINT=
WORKSPACE_ROOT=./workspace
TOOLS_DIR=./tools
MAX_CONCURRENT_RUNS=4
MAX_BOT_HOPS=20
HISTORY_TOKEN_BUDGET=24000
HISTORY_MAX_MESSAGES=80
MEMORY_REFLECTION_DELAY=30
SEED_DEMO_BOTS=true
```

## 13. Seeded demo bots

Created on first start when the bots table is empty and `SEED_DEMO_BOTS=true`:

- **engineer** (`@engineer`): tools `run_shell, read_file, write_file, list_files`. Instructions:
  implement the requested change in the repo at the workspace root on a new branch, run tests,
  commit, push, open a PR with `gh pr create`, then reply with the PR link and mention
  `@reviewer`.
- **reviewer** (`@reviewer`): tools `run_shell, read_file, list_files`. Reviews the PR diff with
  `gh pr diff`, comments with `gh pr review`; if changes are needed, mentions `@engineer` with the
  list; otherwise mentions `@qa`.
- **qa** (`@qa`): tools `run_shell, read_file, list_files`, approval on `run_shell` is off but the
  instructions require `ask_human` before merging. Checks out the PR branch, runs the test suite,
  reports results; on success asks the human for merge approval, then `gh pr merge --squash`,
  then reports done.

Default provider/model for seeds is the first configured provider in the order
openai, anthropic, openrouter, xai, with a sensible default model per provider.

The README walkthrough: clone a repo into `workspace/`, start OpenBot, open a thread with
`@engineer`, send "Add a --version flag to the CLI", watch the hand-offs, approve the merge.

## 14. Testing

- **Backend unit/integration** (pytest, pytest-asyncio, in-memory SQLite, `InMemoryStore`):
  routing rules, hop limit, pending-message follow-up, history rendering, prompt assembly, tool
  registry loading (fixture plugin dir), workspace path escapes, shell tool, memory tools wiring,
  runner end-to-end with `GenericFakeChatModel` scripted to call tools and to trigger
  `ask_human` then resume, API endpoints with httpx `AsyncClient`, SSE stream, webhook
  signing and retry.
- **Provider smoke tests**: one per provider, skipped unless the key is present.
- **Frontend**: `tsc --noEmit`, vitest for the mention parser and SSE reducer, `vite build`.
- **CI**: GitHub Actions runs backend lint (ruff), tests, frontend typecheck, tests, build.

## 15. Out of scope for v1

Accounts and login, cron triggers, inbound webhooks, MCP servers, Docker sandboxing, chat
platform adapters, multi-node deployment. The queue, store, and tool registry interfaces are the
seams for these.
