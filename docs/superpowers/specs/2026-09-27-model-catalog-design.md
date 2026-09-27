# Model catalog from models.dev, model picker, and effort levels: design

Status: agreed 2026-09-27. Builds on the runtime settings layer
(`docs/superpowers/specs/2026-09-17-setup-wizard-design.md`) and the provider factory in
`backend/openbot/runtime/providers.py`.

## Goal

Replace the hardcoded model suggestions with a catalog fetched from https://models.dev/api.json, so
the Settings page and the bot editor offer the current, agent-capable models of OpenAI, Anthropic,
OpenRouter and Ollama, with cost and capabilities visible. Where a model declares reasoning effort
levels, a bot can pin one. Users always keep the option to type any model id. For Ollama the models
installed on the local server come first, followed by the tool-capable models Ollama supports. xAI
keeps its builtin list.

## Facts about the source that shape the design

- models.dev is one JSON document: 223 providers, about 8,170 models, 4.9 MB. The providers in
  scope hold 473 models (OpenRouter 384, OpenAI 50, Anthropic 15, Ollama 24); after the
  agent-fitness filter below about 380 remain (OpenRouter ~312, OpenAI 31, Anthropic 15, Ollama 24).
- Ollama appears in models.dev as `ollama-cloud`: the 24 models Ollama itself serves (gpt-oss,
  qwen3.5, gemma4, deepseek-v4, glm-5.3, kimi, minimax, nemotron...), all tool-capable, with
  context and Ollama Cloud prices. Their ids are Ollama library names (`gpt-oss:20b`), so they are
  also what a user pulls locally. This is the "supported models" list for Ollama; the models
  installed on the local server still come from its `/api/tags` through `/providers`.
- There is no task category (coding, comprehension). There is: `family` (claude-opus, gpt-mini,
  qwen...), capability flags (`reasoning`, `tool_call`, `structured_output`, `attachment`),
  `modalities`, `limit` (context, output), `cost` (USD per million tokens), `release_date`, `status`
  (absent, `beta`, `deprecated`) and `description`.
- `reasoning_options` lists how a model's reasoning is controlled. The `effort` option carries the
  exact allowed values, which differ per model (`low/medium/high`, `none/low/medium/high/xhigh/max`,
  `medium` only, ...). Other option types (`budget_tokens`, `toggle`) are not effort levels.
- The frontend may not call external services (`scripts/check-client-boundaries.py`), so the fetch
  lives in the backend.
- `provider_chat_model` already forwards `model_settings.reasoning_effort` to ChatOpenAI for OpenAI,
  xAI and OpenRouter. The installed `langchain-anthropic` (1.7) accepts the same `reasoning_effort`
  constructor argument on ChatAnthropic.

## Backend

### Storage

Migration `0016_model_catalog` adds table `model_catalog`:

| column | type | notes |
|---|---|---|
| `provider` | String(32), primary key | `openai`, `anthropic`, `openrouter`, `ollama` (from models.dev `ollama-cloud`) |
| `models` | JSON | list of normalized model records |
| `fetched_at` | DateTime(timezone) | when this row was written from a successful fetch |

One row per provider keeps rows small and lets a request read only the provider it needs.

### Agent-fitness filter

A model is kept only when all of these hold; everything else is dropped at ingest so the picker never
offers a model the agent loop cannot use:

- `tool_call` is true (bots call tools on every run);
- `"text"` is in both `modalities.input` and `modalities.output` (drops image, video, audio and
  embedding models);
- `status` is not `deprecated`;
- `limit.context` is at least 32,000 tokens (drops the GPT-3.5 era and small edge models; a bot run
  with system prompt, tools and history does not fit below that).

The thresholds live as constants in `model_catalog.py`. `beta` models are kept and badged.

### Normalized model record

Stored and served as-is. Every other models.dev field is dropped.

| field | from |
|---|---|
| `id` | model key / `id` |
| `name` | `name` |
| `family` | `family`, or `""` |
| `description` | `description`, or `""` |
| `reasoning` | `reasoning` (bool) |
| `effort_levels` | `values` of the `reasoning_options` entry with `type == "effort"`, else `[]` |
| `image_input` | `"image" in modalities.input` |
| `context` | `limit.context` |
| `output` | `limit.output`, or `null` |
| `cost_input`, `cost_output` | `cost.input`, `cost.output` (USD per million tokens), or `null` |
| `release_date` | `release_date`, or `""` |
| `status` | `status`: `null` or `"beta"` |

Entries that are not a mapping or lack an `id` are skipped with a warning; one bad entry never
drops a provider.

### Service: `runtime/model_catalog.py`

`ModelCatalog(sessionmaker, http_client)` with:

- `async get(provider) -> CatalogResult | None`. Reads the provider's row. If the row is missing or
  `fetched_at` is older than `CATALOG_TTL` (24 hours), it schedules one refresh (below) and returns
  what it has: the row (marked `stale=True`) or `None`. It never awaits the network.
- `async refresh()`. Downloads models.dev with the shared `services.http_client` (timeout 20 s),
  filters and normalizes the four providers (`CATALOG_SOURCES = {"openai": "openai", "anthropic":
  "anthropic", "openrouter": "openrouter", "ollama": "ollama-cloud"}`) and upserts the four rows in
  one transaction with `fetched_at = now`. Any failure (network, HTTP status, JSON, schema) is logged at warning level and
  leaves the existing rows untouched. An `asyncio.Lock` plus a "refresh in flight" flag ensure
  concurrent `get` calls share one fetch; the task is created with `asyncio.create_task` and tracked
  so `close_services` can cancel it.
- Startup (`main.py`) calls `get("openrouter")` once after migrations (any provider would do; one
  refresh fills all four rows), so a fresh install starts fetching before the first page load. Tests get a catalog whose http client is a
  `MockTransport`; the startup call is skipped when `services.http_client` is `None`.

### API

`GET /api/v1/models?provider=<id>` (router `api/models.py`), provider one of `openai`, `anthropic`,
`openrouter`, `ollama`.

```json
{
  "provider": "openrouter",
  "source": "catalog",
  "stale": false,
  "fetched_at": "2026-09-27T15:00:00Z",
  "models": [ { "id": "...", "name": "...", "cost_input": 1.0, "cost_output": 5.0, ... } ]
}
```

- `source` is `"catalog"` when a row exists. When none exists yet (first boot offline, or fetch
  failing), `source` is `"builtin"`, `fetched_at` is `null`, and `models` is built from
  `PROVIDER_MODELS[provider]` with `id == name` and every other field empty, null or false, so the
  picker degrades to today's list rather than an empty panel.
- `stale` is true when the row is older than the TTL (a refresh has been scheduled) or the source is
  builtin.
- Unknown provider, `auto` and `xai` return 422; xAI keeps its builtin list in `/providers`.

`/providers` is unchanged. Its short `models` list becomes the "Suggested" group the picker pins at
the top, and `default_model` keeps its meaning.

### Only configured providers list models (amendment, 2026-09-27)

A provider whose key (or, for Ollama, base URL) is not set gets no model list: `ModelsOut` carries
`configured: bool` (from `provider_configured`), and when it is false the endpoint returns
`models: []` without touching the catalog or scheduling a refresh. Models of an unconfigured
provider that are reachable through OpenRouter are already listed under `openrouter` (their ids are
`anthropic/...`, `openai/...`), so nothing more is needed for that case. The picker shows
"<Provider> is not configured. Add its API key in Settings." (Ollama: "... Set its base URL in
Settings.") instead of chips and rows, and suppresses the "not in catalog" note. The provider
dropdown in the bot editor keeps listing unconfigured providers with its existing "(not configured)"
label, so a user can still type a model id for a key they are about to add. For Ollama that list is the installed models when
the server is reachable (today's behaviour), so the pinned group is the installed set.

### Effort at runtime

`provider_chat_model` passes `reasoning_effort` from `model_settings` to ChatAnthropic as well as to
ChatOpenAI. Ollama ignores it, as today. Because `model_factory` also serves memory reflection and
thread renaming, a bot's effort applies to those calls too; this matches how `temperature` and
`max_tokens` already behave and is accepted.

`BotCreate` and `BotUpdate` validate that `model_settings.reasoning_effort`, when present, is a
non-empty string. The check that the value is one of the model's levels lives in the UI only: users
may type a model that is not in the catalog, and the provider is the authority on what it accepts.

### Tests (backend)

- `test_model_catalog.py`: filter and normalizer on a fixture slice of models.dev JSON
  (`tests/fixtures/models_dev_sample.json`, a few models per provider covering effort, budget-only,
  toggle, deprecated, no tool calling, image-only output, small context, missing fields, one
  malformed entry, and the `ollama-cloud` to `ollama` mapping); `get` on empty DB schedules a
  refresh and returns `None`; `refresh` with `MockTransport` writes four rows; a stale row is served
  and triggers one refresh even under concurrent `get` calls; a failing fetch keeps the old rows.
- `test_models_api.py`: builtin fallback shape, catalog shape, 422 for `auto`/`xai`/unknown.
- `test_providers.py`: Anthropic receives `reasoning_effort`.

## Frontend

### `ModelPicker` component (`components/ModelPicker.tsx`)

A combobox that replaces the `<datalist>` in the bot editor. Props: `provider`, `value`,
`onChange(value)`, `suggested: string[]` (from `/providers`), `suggestedLabel` ("Suggested", or
"Installed" for Ollama), optional `id`/`required`.

- The input is plain text and is the source of truth: whatever is typed is the model id, whether or
  not it matches a catalog row. A value that matches no row shows a quiet "not in catalog" note
  under the field, never an error.
- Focus or typing opens the panel. Typing filters rows case-insensitively by substring on `id`,
  `name` and `family`. Empty text shows everything.
- Rows are grouped by `family` (models with no family fall under "Other"). Families are ordered by
  their newest `release_date`, newest first; within a family, newest first. Models in `suggested`
  appear in a pinned group at the top (`suggestedLabel`) and are not repeated below. An installed
  Ollama model that is also in the catalog shows the catalog's badges in the pinned group; one that
  is not (a custom or older tag) shows just its name.
- Filter chips in the panel header: Reasoning, Vision. Active chips narrow the list in addition to
  the typed text. Every listed model supports tools, so there is no tools chip.
- A "Sort" control in the panel header switches between newest first (default) and cheapest first
  (by `cost_output`, unknown cost last); grouping by family is kept in both.
- Each row shows the `id` (monospace), the `name` when it differs, the cost, and badges. Cost is
  shown as `$<in> / $<out> per M tokens` (input / output, from `cost_input` and `cost_output`,
  trimmed to two significant decimals, `free` when both are 0, omitted when unknown). For Ollama the
  cost is suffixed "on Ollama Cloud", since a locally pulled copy costs nothing per token, and rows
  outside the installed group carry a muted "not installed" note. Badges:
  `reasoning`, `effort` (when `effort_levels` is non-empty), `vision`, context (`200k`), `beta`.
  The `description` is a second muted line when present.
- Keyboard: ArrowUp/ArrowDown move the highlight across groups, Enter picks, Escape closes,
  Tab closes and keeps the typed text. Mouse down on a row picks it.
- Rows are rendered plainly, no virtualization: about 312 rows for OpenRouter after filtering.
- Data: `useQuery(["models", provider], () => Api.getModels(provider))`, `staleTime` 5 minutes.
  While loading, the panel shows a spinner row. When the response is `stale` or `builtin`, the
  panel header shows "Catalog updating…" in muted text.

The picker follows the mention popup in `Composer.tsx` for panel styling and `role="listbox"` /
`role="option"` markup.

### Where it is used

- **Bot editor** (`BotEditorPage.tsx`): the Model field for `openai`, `anthropic`, `openrouter` and
  `ollama` (installed models pinned, then the supported list). xAI keeps the current datalist of its
  builtin list. The auto provider keeps the disabled input.
- **Settings page** (`SettingsPage.tsx`): the "Default bot model" tunable (`item.key ===
  "bot_model"`) renders the picker scoped to `openrouter` instead of the plain input. The value
  still flows through the existing draft mechanism, so saving and reset are unchanged.

### Effort control (bot editor)

Below the Model field, an "Effort" `Select` appears only when the effective model has a non-empty
`effort_levels`:

- For an explicit provider, the effective model is `form.model` looked up in that provider's
  catalog.
- For the auto provider, it is the resolved default (`auto.default_model`, formatted
  `provider/model`) looked up in that provider's catalog.
- Options are "Default (provider decides)" plus that model's levels in catalog order. Choosing
  Default deletes `reasoning_effort` from `model_settings`; choosing a level sets it.
- When the model changes and the saved value is not among the new model's levels, the key is removed
  so a stale value is never sent. A previously saved value for a model without effort levels is
  also removed on save.

The Model field also shows a one-line warning when an OpenRouter key is configured and the provider
is another cloud provider: "With an OpenRouter key configured, cloud bots run on the default
OpenRouter model." The routing rule itself is out of scope (see below). The frontend learns this
from `/providers`: `openrouter.configured`.

### Types and client

`types.ts` adds `CatalogModel` and `ModelsOut`. `client.ts` adds
`getModels(provider) => api<ModelsOut>(`/models?provider=${provider}`)`.

### Tests (frontend)

- `lib/modelCatalog.test.ts` for pure helpers: filtering, grouping order, cheapest-first sort,
  suggested pinning, cost formatting, context formatting.
- `components/ModelPicker.test.tsx` (jsdom): typing filters, free text passes through with the
  "not in catalog" note, keyboard selection, chips narrow the list, cost shown, stale hint.
- `pages/BotEditorPage.test.tsx`: effort select appears only for effort-capable models, options
  match the model's levels, changing model clears an incompatible value, Default removes the key.
- `pages/SettingsPage.test.tsx`: `bot_model` renders the picker and saves through PATCH.

## Out of scope (follow-ups)

- **OpenRouter rerouting.** `effective_bot_profile` sends every explicit cloud bot to OpenRouter's
  global default model when an OpenRouter key exists, so a per-bot model is ignored in that case.
  This design surfaces the fact in the editor but does not change the rule.
- The setup wizard's default-model input stays free text.
- Effort for models that expose only `budget_tokens` or `toggle`.
- xAI and the other models.dev providers; xAI could join the catalog by adding its id to
  `CATALOG_SOURCES`.
- Pulling an Ollama model from the UI; the picker only says which ones are not installed.
- Tuning the agent-fitness thresholds from Settings.
- A manual "refresh now" button; the 24-hour TTL is the only trigger.

## Error handling summary

- A failed or slow models.dev fetch never fails a request: the API serves the stale rows or the
  builtin list, and the UI shows a neutral "Catalog updating…" hint.
- Malformed catalog entries are skipped one at a time with a warning.
- Effort values are validated for type on the backend and for membership in the UI.

## Docs and rollout

- README configuration section: a paragraph on the catalog (source, 24-hour refresh, agent-fitness
  filter, builtin fallback) and on `model_settings.reasoning_effort` now applying to Anthropic.
- Existing bots are unaffected: `reasoning_effort` already lives in `model_settings`, so saved
  values keep working and now show in the Effort select.
