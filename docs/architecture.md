# OpenBot Architecture: Mailboxes, Threads, Runs and Memory

Status: living document. Written 2026-09-16 against commit `2ad5ca1`; gap register updated the same day
after G1 to G6 were implemented.
Companion to the original design spec in `docs/superpowers/specs/2026-09-13-openbot-design.md`,
which this document does not replace; it goes deeper on the runtime model and records where the
code and the intended model still differ.

Each section has three parts where they differ:

- **Model**: the intended architecture, as agreed on 2026-09-16.
- **As built**: what the code does today, with file references.
- **Gap**: where the two disagree, the consequence, and the proposed change.

---

## 1. Vocabulary

| Term | Meaning |
|---|---|
| **Actor** | Anyone who can send or receive messages: a **bot** (LLM agent), the **human** operator (`@you`), or an **external** system reached by webhook. One row in `actors`. |
| **Mailbox** | An actor's inbox: the rows in `inbox_items` whose `actor_id` is that actor. Every actor has exactly one. |
| **Inbox item** | One unit of work in a mailbox. Three kinds: `message` (a thread message to react to), `question` (a bot is waiting for an answer), `resume` (the answer, addressed back to the bot). |
| **Thread** | A conversation that represents one task and its context. Threads cut across mailboxes: one thread's messages land in many mailboxes. |
| **Message** | An immutable post in a thread by an actor or the system. Messages are the only content that persists across runs. |
| **Run** | One execution of a bot's agent loop, in one thread, triggered by one or more inbox items. The unit of scheduling, cost accounting and cancellation. |
| **Run event** | A step inside a run: tool call, tool result, text, interrupt, resumed, error, message. |
| **Hop** | The count of bot-to-bot hand-offs since the last human message. Bounds runaway delegation. |
| **Memory** | Durable, bot-scoped knowledge in the LangGraph store. Not thread state. |
| **Tool source** | Where a selectable tool comes from: the built-ins, plugin modules in `TOOLS_DIR`, or an MCP server (`mcp:<name>`, tools named `<name>__<tool>`; see `docs/superpowers/specs/2026-09-17-mcp-design.md`). All land in one registry, so per-bot selection and approvals work the same. |

## 2. The model in one paragraph

Every actor owns a mailbox. Posting a message to a thread fans out inbox items to the mailboxes of
the actors who should react. A bot's worker takes items from its mailbox one at a time in arrival
order. Each item names a thread; the bot switches between threads as their items arrive, but never
works on two at once. Before calling the LLM, the bot *unrolls* the thread: it rebuilds the model's
context from the thread's persisted messages, the bot's own memories, the participant roster and the
thread's working directory. The LLM's reply is posted back to the thread, which fans out again. Bots
therefore carry no conversational state between runs. The two things that do persist are the thread
itself, which is the task's context, and the bot's memory, which holds what the bot has learned about
how to do its job and must never hold facts that are only true for one thread.

## 3. Data model

All application tables live in the SQL database configured by `DATABASE_URL`
(`backend/openbot/db/models.py`). LangGraph keeps two more stores beside it: a **checkpointer** for
in-flight agent state and a **store** for memories and the message index
(`backend/openbot/runtime/persistence.py`, file `<db>.langgraph.db` on SQLite).

```
actors ─┬─ bot_profiles        (instructions, provider/model, tools, approval_tools, memory_enabled)
        └─ external_profiles   (webhook_url, webhook_secret)

threads ── thread_participants ── actors
   │
   ├── messages        (sender, content, mentions, hop, run_id, metadata)
   ├── runs            (actor_id, status, interrupt, error, usage counters)
   │      └── run_events (seq, type, payload)
   └── inbox_items     (actor_id, kind, message_id | run_id, payload, status)

LangGraph checkpointer   keyed by run.id           (agent transcript of one run)
LangGraph store          ("bots", bot_id, "memories")   long-term memory
                         ("threads", thread_id, "messages")  semantic index of every message
```

**Model.** Every inbox item belongs to a thread. An inbox item is a pointer into a thread, never a
copy of content; the thread is the single source of truth for what was said.

**As built.** `inbox_items.thread_id` is `NOT NULL` (migration 0006) and every code path that creates
an item sets it (`delivery.post_message`, `delivery.deliver_question`, `actors.enqueue_resume`).
`message` items carry `message_id`; `question` and `resume` items carry `run_id`.

**Gap G1 (closed).** The column used to be nullable, which allowed a threadless item the model
forbids. The schema now enforces the invariant.

## 4. Lifecycle of a message

The whole system is one loop: post, route, enqueue, pick, run, reply, post.

```
 human / bot / tool               delivery.post_message            ActorSystem            Runner
 ───────────────────              ─────────────────────            ───────────            ──────
 content "@engineer do X" ─────▶  1 parse @mentions
                                  2 resolve targets
                                  3 insert Message (hop = n)
                                  4 add targets as participants
                                  5 hop limit check
                                  6 insert InboxItems:
                                      message → each target bot
                                      message → each human/external
                                                participant (not sender)
                                  7 index message in store
                                  8 publish message.created,
                                    inbox.updated (SSE)
                                  9 notify(actor_id) ─────────────▶ wake worker
                                                                    BotActor._pick():
                                                                      oldest queued item whose
                                                                      thread is not parked
                                                                      + all queued items for
                                                                        that same thread
                                                                      → new Run(queued)
                                                                    acquire semaphore ─────▶ execute(run)
                                                                                             _prepare: unroll thread
                                                                                             create_agent + middleware
                                                                                             stream; record run_events
                                                                                             reply → post_message(hop+1) ─┐
                                                                                             set completed; reflect      │
                                  ◀────────────────────────────────────────────────────────────────────────────────────┘
```

### 4.1 Routing (`runtime/router.py`, `delivery.post_message`)

- Targets are the bots named by `@handle` in the content (or passed explicitly via `to_handles`),
  in order, deduplicated, enabled, and never the sender.
- A **bot** message hands off to **one** bot: the first mention that can act (enabled, not the
  sender). Later `@handles` are recorded in `Message.mentions` (so the scoped view of that bot still
  includes the message once it is woken) but wake nobody. "@engineer fix these. @qa retest after the
  fixes" used to wake both at once, and QA had nothing to test. Human messages keep the full fan-out.
- A **human** message with no mention goes to the thread's default bot, falling back to
  `@chief_of_staff`. A message with no mention in a thread that has exactly one bot goes to that bot.
- A **bot** message with no mention wakes nobody. This is how a bot ends a conversation.
- A message from the **system** (`sender=None`) wakes nobody. Restart and failure notices use this.
- Mentioned bots that are not yet participants are added to the thread.

### 4.2 Fan-out to mailboxes

For each posted message (including a hop-limit notice):

- one `message` item per target bot;
- one `message` item per human or external participant other than the sender, so the UI inbox and
  webhook subscribers see everything in their threads.

Bots that are participants but not mentioned get nothing. That is deliberate: being in a thread does
not mean being woken by every message in it.

### 4.3 Hop limit

`Message.hop` is 0 for human posts and `max(trigger hops) + 1` for a bot reply. When a bot reply
mentions bots and `hop >= MAX_BOT_HOPS` (default 20), the targets are dropped and one system notice
is posted per thread until a human message resets the flag (`threads.hop_limit_notified`). This is
the only brake on two bots ping-ponging forever.

## 5. Scheduling: how a bot drains its mailbox

**Model.** A bot processes one inbox item at a time, in arrival order. Items may belong to different
threads, so the bot interleaves threads: thread 1, thread 2, thread 1, thread 3. It never runs two
threads concurrently. Different bots run concurrently.

**As built** (`runtime/actors.py`).

- `ActorSystem` lazily creates one `BotActor` worker per bot on the first `notify()`. The worker is
  an asyncio task with a wake event. There is exactly one worker per bot, so a bot has at most one
  run in flight at any moment. This matches the model.
- `_pick()` reads all `queued` items for the bot ordered by `created_at`, skips any `message` item
  whose thread has a run in `waiting_human` for this bot (**parking**, see §7), and chooses the
  oldest remaining. Ordering by the oldest item means a busy thread cannot starve a quiet one.
- If the chosen item is a `resume`, it alone becomes the batch and resumes the existing run.
- Otherwise **every queued `message` item for the same thread** is grouped with it into **one new
  run**. Three messages that arrived for the engineer in one thread while it was busy produce one
  run with three trigger messages, not three runs.
- A global `asyncio.Semaphore(MAX_CONCURRENT_RUNS)` (default 4) caps runs across all bots. The
  worker acquires a slot *before* picking, so a bot waiting for a slot owns no run row.
- Items move `queued → processing → done | cancelled | failed`. The run moves
  `queued → running → completed | failed | cancelled | waiting_human`.

**Gap G2 (closed, wording).** The model says "one message at a time"; the code says "one
thread's pending messages at a time". Because the run unrolls the whole thread anyway, a run per
message would make the bot answer messages it has already seen in the previous run's history, and
would double the model calls for no new information. Coalescing is the right behavior and the design
spec now says so. The invariant is: *a bot has at most one run in flight; a run serves exactly one
thread; every queued message for that thread at pick time joins that run.*

**Gap G3 (closed).** The run used to be created and its items flipped to `processing` *before* the
semaphore was acquired, so under load a bot could hold a phantom `queued` run that blocked
`DELETE /bots/{id}` and drew an active card. The worker now takes the slot first, then picks.

## 6. Unrolling the thread: what the LLM sees

**Model.** A bot has no memory of a thread between runs. Each run rebuilds context from persisted
truth: the thread's messages, the bot's memories relevant to the trigger, the participants, and the
working directory. How much of the thread a bot sees depends on its role in it. The thread's
**default bot** coordinates, so it sees the whole conversation. So does the **only bot** in a thread,
since nobody is delegating to it. Every other bot is a **delegate** and sees only the messages
addressed to it plus its own earlier replies: a hand-off must be self-contained, and two tools,
`read_history` and `recall_messages`, fetch the rest of the thread when it is not. This keeps each
delegate's call hand-off-sized instead of thread-sized and keeps one bot's chatter out of another's
context.

**As built** (`runtime/runner.py::_prepare`, `runtime/prompt.py`; scoping added 2026-09-16).

The scope decision: `scoped = not is_default and len(bots_in_thread) > 1`, where the default bot is
the thread's `default_bot_actor_id` falling back to `@chief_of_staff`. A scoped bot's candidate
messages are those it sent, those whose `mentions` include it, and this run's triggers. The count of
everything else is reported to the model as "N other messages exist but are not shown", with the
two retrieval tools named. Direct-post threads (§3) have one bot and are therefore never scoped.
The seeded chief is told that delegates see only the message addressed to them and that every
hand-off must carry goal, paths or PR number, acceptance criteria and what to report back; the
engineer, reviewer and QA are told what they see and which tools fetch more.

The system prompt contains, in order:

1. Identity (`name`, `@handle`, description) and the bot's instructions verbatim.
2. Platform rules: who is in the thread, how mentions wake bots, the default bot, delegation must
   happen in this thread, `ask_human` pauses the run, approvals, memory tools, workspace root, tool list.
3. Roster of every other enabled bot with handle and description.
4. Up to eight memories from the bot's namespace, ranked by semantic similarity to the concatenated
   text of the trigger messages.

The message history is built from the newest messages backwards until either
`HISTORY_TOKEN_BUDGET` (24k, estimated at chars/4) or `HISTORY_MAX_MESSAGES` (80) is hit. The bot's
own earlier replies become `AIMessage`; everything else becomes `HumanMessage("[name]: text")`, with
consecutive foreign messages merged into one. The trigger messages, the ones whose inbox items woke
this run, render as `[name] (new): text`, and the system prompt tells the model those are what it
is answering. If anything was cut, the prompt says how many older
messages exist and points at `read_history` (chronological paging) and `recall_messages` (semantic
search over the thread's index in the store).

The agent's own transcript during the run (tool calls, tool results, intermediate thoughts) lives
in the LangGraph checkpointer under `configurable.thread_id = run.id`. It is used for `ask_human`
resumption (§7) and for memory reflection, and is never read by a later run. A later run in the same
thread starts from the thread messages only. The checkpoint is deleted as soon as the run is
terminal (completed, failed, or cancelled, including cancellation from the API and restart recovery);
only `waiting_human` runs keep theirs.

Middleware bounds each run: prompt caching breakpoints, `ModelCallLimitMiddleware`
(`MAX_MODEL_CALLS_PER_RUN`, default 40, overridable per bot in `model_settings.max_model_calls`),
`ContextEditingMiddleware` that blanks old tool results past `CONTEXT_TRIGGER_TOKENS` (60k), and
`HumanInTheLoopMiddleware` for tools listed in `approval_tools`.

**Gap G4 (closed).** Trigger messages used to be unmarked, so in a thread where several bots post
between two of this bot's runs, or where several triggers were coalesced (§5), the model had to guess
which messages it was answering. They are now marked `(new)`.

**Gap G5 (closed).** Checkpoints keyed by `run.id` used to be kept forever. They are now deleted when
the run reaches a terminal state, after reflection has taken its copy of the transcript.

## 7. Pausing for a human: `ask_human` and approvals

A run pauses when the agent calls `ask_human` or a tool in `approval_tools`. LangGraph raises an
interrupt; the runner records it, sets the run to `waiting_human`, stores the question on the run,
and posts a `question` item into the mailbox of every human and external participant
(`delivery.deliver_question`). The bot's worker moves on to other threads.

While a bot has a `waiting_human` run in a thread, that thread is **parked** for that bot: new
`message` items for it stay `queued` and `_pick` skips them. This keeps one thread's state machine
linear. Other threads are unaffected.

`POST /runs/{id}/resume` validates the answer against the interrupt kind, marks the human's
`question` item done, and enqueues a `resume` item in the bot's mailbox. The worker picks it,
resumes the checkpointed agent with `Command(resume=value)`, and the run continues under the same
run id. Usage from both segments is summed onto the run.

Restart: `waiting_human` runs survive because their state is in the checkpointer.
`running` and `queued` runs become `failed` with "server restarted" and a system notice is posted.

## 8. State: what is stateless, what is not

| Scope | State | Where | Lifetime |
|---|---|---|---|
| Run | Agent transcript, interrupt, usage counters, events | checkpointer, `runs`, `run_events` | Created per run. Transcript needed until resume and reflection are done (G5). |
| Thread | Messages, participants, default bot, working directory, hop-limit flag, semantic message index | `threads`, `messages`, `thread_participants`, store | Life of the thread. This is the task's context. |
| Bot | Profile (instructions, model, tools), **memories**, pending reflection batch | `actors`, `bot_profiles`, store, in-process | Life of the bot. Memories are the only learned state. |
| Process | Workers, wake events, semaphore, event bus subscribers, reflection timers | memory | Lost on restart; rebuilt from the tables (`ActorSystem.start`). |

A bot is stateless **with respect to threads**: nothing about a thread lives in the bot. It is
stateful **with respect to itself**: its memories change how it behaves in every thread. That is the
precise sense in which "bots are stateless" is both true and not true.

## 9. Memory

**Model.** Memory is per bot and global across threads. It holds knowledge about *how the bot does
its job*: "always wait for CI before merging", "the team uses squash merges", "the human prefers
short status updates". It must never hold facts that are only true inside one thread: "in this
thread use camelCase" belongs in the thread, where unrolling delivers it for free.

**As built** (`runtime/memory.py`).

Two write paths, one namespace `("bots", bot_id, "memories")`:

- **Explicit.** The agent calls `manage_memory` (LangMem) during a run. Tool instructions ask for
  "durable facts, preferences, decisions and lessons you will need in future conversations".
- **Reflection.** After each completed run of a bot with `memory_enabled`, the runner hands the
  run's full agent transcript to `MemoryReflector.schedule(bot, messages, thread_id=...)`. The
  reflector appends it to a pending list keyed by `(bot, thread)` and restarts that key's 30s timer
  (`MEMORY_REFLECTION_DELAY`). When the timer fires, `create_memory_store_manager` reads that one
  thread's transcripts, under an explicit instruction to extract only bot-level knowledge, and
  inserts new memories (inserts only, no deletes). On shutdown, pending batches are flushed with a
  10s timeout. Both the reflection instruction and the `manage_memory` tool carry the same rule text
  (`memory.MEMORY_SCOPE_RULE`).

Two read paths:

- Prompt injection: top eight memories by similarity to the trigger text (§6).
- The `search_memory` tool, on demand.

Because the namespace is global, a memory written in thread A is visible to the very next run in
thread B. That is intended.

**Gap G6 (mostly closed).** Until 2026-09-16 nothing enforced the bot-not-thread rule: the
`manage_memory` instructions did not mention threads, reflection ran with LangMem's default
extraction prompt (which happily extracts "the PR number is 16"), and the per-bot debounce merged
transcripts from different threads into one extraction pass whenever a bot finished runs in two
threads within 30 seconds. Items 1 to 3 below are done; item 4 remains.

1. Done. Reflection carries an explicit instruction: only durable, bot-level knowledge about how to
   work; never task state, identifiers, file names or decisions specific to one thread.
2. Done. Reflection is scheduled per `(bot, thread)`, so one pass never sees two threads. The
   debounce is kept so a burst of runs in one thread still reflects once.
3. Done. The `manage_memory` tool carries the same rule.
4. Open. Enable deletes/updates in reflection so wrong or superseded memories can be retired, with
   the same guardrail text. Size: medium (needs testing against existing memories).

The rule is still a prompt instruction rather than a mechanical filter; the model can ignore it.
Whether that is enough should be judged by reading the memories the seeded team accumulates over
the next weeks.

**Gap G7.** Pending reflection batches are in-process. A crash loses them; only a clean shutdown
flushes. Acceptable for now; if reflection becomes load-bearing, persist the pending run ids and
reflect from checkpoints on start. Size: medium.

## 10. Concurrency and consistency

What runs in parallel:

- Different bots, up to `MAX_CONCURRENT_RUNS` in total.
- External webhook deliveries (their own workers, with retries).
- API requests and SSE fan-out.

What is serialized:

- Everything a single bot does, across all threads (§5).
- Everything in a single thread *for a single bot*. Two different bots can run in the same thread at
  the same time, each posting replies. Message order is by `created_at`, so their replies interleave
  in the thread as they land.

Races the code already handles: a cancel that lands between `_pick` and `_process` (items already
`cancelled` are not overwritten with `done`); two `notify()` calls creating a worker for the same bot
(re-checked after the await); a webhook actor losing its URL mid-delivery; restart with `processing`
items or `queued` runs.

Correctness argument for interleaving: because a run reads the thread from the database at
`_prepare` time and writes only by posting messages, two bots in the same thread cannot corrupt each
other's state. The worst case is both replying to the same human message, which routing already
makes rare (only mentioned bots wake).

**Gap G8.** Single process. The event bus is in-memory, workers are asyncio tasks, and the semaphore
is per process. Two backend processes against one database would each start a worker per bot and
double-run mailboxes. This is out of scope today and should stay documented as a constraint until a
leased-item scheme (`processing` with owner and lease expiry) is needed.

## 11. Invariants

These hold in the code today unless marked, and the target architecture keeps all of them.

1. Every inbox item belongs to exactly one thread. *(Enforced by schema since migration 0006.)*
2. An inbox item points at a message or a run; it never carries content of its own.
3. A bot has at most one run in flight at any time.
4. A run belongs to exactly one bot and exactly one thread.
5. All queued `message` items for one thread at pick time join the same run.
6. A thread is parked for a bot while that bot has a `waiting_human` run in it.
7. A run reads thread state only at `_prepare`; it writes thread state only by posting messages.
8. A bot's reply wakes only the bots it mentions. An unmentioned bot reply ends the exchange.
9. A message from the system wakes nobody.
10. Memory is bot-scoped and must contain no thread-scoped facts. *(Instructed, not mechanically enforced: G6.)*
11. Bot-to-bot hops are bounded by `MAX_BOT_HOPS` and reset by any human message.
12. Restart never loses a message or an unanswered question; it may fail an in-flight run and says so
    in the thread.

## 12. Gap register and proposed order

| # | Gap | Status | Change |
|---|---|---|---|
| G6 | Memory scope not enforced; reflection merges threads | Closed (items 1 to 3); item 4 open | Reflection instructions, per-thread reflection batches, tool instruction |
| G4 | Trigger messages unmarked in history | Closed | Trigger messages render as `[name] (new): text` |
| G1 | `inbox_items.thread_id` nullable | Closed | Migration 0006, `NOT NULL` |
| G3 | Run created before semaphore | Closed | Slot acquired before pick |
| G5 | Run checkpoints never deleted | Closed | Deleted on terminal state, API cancel, restart recovery |
| G2 | Spec wording says "one message" | Closed | Spec says "one thread's pending messages at a time" |
| G7 | Reflection batches in-process only | Open, medium | Persist pending run ids |
| G8 | Single-process assumption | Open, large, deferred | Leased inbox items, shared bus |

## 13. Target architecture, stated plainly

- Actors own mailboxes. Threads own context. Runs own execution. Memory owns learning.
- A message is posted to a thread and fans out to the mailboxes of the actors who should react.
- A bot drains its mailbox one thread at a time, interleaving threads in arrival order, coalescing
  everything pending for the thread it picks, and skipping threads where it is waiting on a human.
- Before each run the bot unrolls the thread from persisted messages plus its own memories. Nothing
  about the thread survives inside the bot between runs.
- Memory is the bot's professional knowledge, shared across every thread it works in, and is the one
  thing that makes a bot more than a stateless function of its thread. Thread-specific facts live in
  the thread.
- Humans and external systems are actors with mailboxes too. They differ from bots only in that no
  LLM drains their mailbox: the UI and webhooks do.
