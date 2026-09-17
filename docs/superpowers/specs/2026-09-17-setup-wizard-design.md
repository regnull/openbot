# Minimal `.env`, settings in the database, first-run setup wizard: design

Status: agreed 2026-09-17. Builds on the runtime settings layer (PR #28) and the MCP store.

## Goal

A fresh checkout starts with `make setup && make run`: `.env` is a copy of `.env.example` holding
only what the process needs before it can read its own database. Everything an operator configures
lives in the database and is edited in Settings. If the minimum configuration to do useful work is
missing, the UI shows a setup wizard every time it loads until it is met.

## What stays in `.env`

Only settings the process needs before, or independently of, the database, or that a library reads
from the environment at import:

| setting | why it stays |
|---|---|
| `DATABASE_URL` | where the database is |
| `SECRET_KEY` / `SECRET_KEY_FILE` | decrypts every stored secret (provider keys, MCP headers, OAuth tokens); generated once when unset |
| `OPENBOT_API_KEY` | gates the API the UI talks to |
| `WORKSPACE_ROOT`, `TOOLS_DIR`, `FRONTEND_DIST`, `MCP_CONFIG` | paths resolved at boot |
| `PUBLIC_URL`, `CORS_ORIGINS` | how the process is reached; CORS is configured at app construction |
| `LOG_LEVEL`, `LOG_FILE` | logging is configured before anything else |
| `MAX_CONCURRENT_RUNS`, `SEED_DEMO_BOTS` | boot-time behaviour |
| `LANGSMITH_*` | read by the LangSmith SDK from the environment |
| `WEBHOOK_RETRY_DELAYS` | infrastructure |

Provider API keys, Ollama, embeddings, the default model and every tunable are no longer in
`.env.example`. If an operator still sets them in `.env` they work as the environment layer under
database overrides, exactly as before; they are simply not the recommended place.

`MCP_TOKEN_KEY` / `MCP_TOKEN_KEY_FILE` remain as deprecated aliases of `SECRET_KEY` /
`SECRET_KEY_FILE`; an existing `mcp_token.key` is picked up so stored MCP credentials keep working.

## What moves to the database

New tunable groups in `app_settings`, edited on the Settings page like the existing ones:

- **Providers**: `openai_api_key`, `anthropic_api_key`, `openrouter_api_key`, `xai_api_key`
  (secret), `ollama_base_url`, `ollama_model`.
- **Embeddings**: `embedding_model` (`provider:model`, or empty for no semantic memory),
  `embedding_dims`.
- **Server**: `public_url` is *not* moved (needed to build redirect URIs before settings load is
  irrelevant, but it describes the deployment, not a preference).

Secret tunables are stored Fernet-encrypted as `{"enc": "..."}` with the secret key, returned masked
(`••••••••`) with an `is_set` flag, and a masked value sent back is ignored. Everything else is as
before: validated like the environment, applied to the live `Settings` object, re-applied at startup.

Applying has two side effects:

- **Embeddings**: changing `embedding_model` or `embedding_dims` reopens the LangGraph store with the
  new index (the checkpointer is untouched), so semantic memory works without a restart. Existing
  vectors written with different dimensions are not migrated; on a fresh install there are none.
- **Setup completion**: after any update, if the minimum configuration is now met, the database has
  no bots, and `SEED_DEMO_BOTS` is on, the demo team is seeded. Boot skips seeding when no provider
  is configured, so this is where a fresh install gets its bots.

## Minimum configuration

`GET /api/v1/setup/status` reports:

- `chat`: a chat provider is usable: any provider API key set, or Ollama base URL set. Lists which.
- `embeddings`: an explicit choice: `embedding_model` empty (semantic memory off) or its provider
  configured (its key set, or Ollama for `ollama:*`).
- `complete`: both.

## Wizard

The frontend fetches the status on load (inside the API-key gate, before routing). While
`complete` is false it renders the wizard full-screen instead of the app, on every load:

1. **Chat provider.** Pick one: OpenRouter, OpenAI, Anthropic, xAI (paste a key; OpenRouter also
   sets the default bot model, prefilled) or Ollama (base URL, prefilled `http://localhost:11434`,
   and model). More can be added later in Settings.
2. **Embeddings.** Pick one: OpenAI `text-embedding-3-small` (1536; asks for the OpenAI key if step
   1 did not supply one), Ollama (model, default `nomic-embed-text`, dims 768), or none.
3. **Finish.** One `PATCH /settings` with the collected values, then the status is re-fetched; when
   complete the app loads. Errors from the server are shown inline.

Settings page: the new groups render like the others; secret fields are password inputs that show
"set" / "not set", send a value only when changed, and reset to the environment value like any
other field.

## Setup

`make setup` already copies `.env.example` to `.env` when absent (`cp -n`). The example's defaults
must start the server with SQLite and no keys, which they do; the wizard then takes over.

## Tests

- Secret tunables: encrypted at rest (plaintext absent from the row), masked in the listing with
  `is_set`, a masked value sent back is a no-op, reset restores the environment value.
- Setup status: incomplete on a fresh install; complete after an OpenRouter key and an explicit
  embeddings choice; Ollama alone counts; embeddings "none" counts; embeddings whose provider has no
  key does not.
- Completion seeds the demo team once.
- Embedding change reopens the store with an index.
- Secret key resolution falls back to an existing `mcp_token.key`.
- `.env.example` contains no provider keys and starts the server (existing hermetic tests cover this).
- Frontend: wizard payload builder and status gate helper.

## Out of scope

Editing `.env` from the browser; per-user settings; migrating existing vectors when embedding
dimensions change.
