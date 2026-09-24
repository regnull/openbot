# Client boundary audit

Status: completed 2026-09. This complements `docs/architecture.md`, which documents the
backend mailbox/thread/run runtime model.

## Boundary map

| Boundary | Presentation/input responsibilities | Backend-owned responsibilities |
|---|---|---|
| `backend/openbot/api/` + `backend/openbot/runtime/` | N/A | HTTP contracts, validation, routing, orchestration, persistence, workers, provider/tool/MCP integrations, memory, scheduling, delivery, and authorization. |
| `frontend/src/` (browser/Vite renderer) | React views, form state, accessibility, local display formatting, API/SSE wiring, and transient UI state. | None. It calls `/api/v1` and must not access databases, provider SDKs, filesystem, subprocesses, or integrations directly. |
| `frontend/electron/` | Window lifecycle, secure navigation, preload isolation, packaged-app presentation shell. | Starting/stopping the packaged backend is deployment/process supervision, not domain orchestration; it exposes no domain API to the renderer. |
| `tools/` and `backend/openbot/tools/` | N/A | Tool registration/execution and integrations. `tools/` is loaded by the backend; it is not client code. |
| `scripts/` and Make targets | Developer/deployment process entry points. | Local process supervision only; production behavior remains in the backend. |

## Findings and decisions

* The renderer's only network transport is `frontend/src/api/client.ts` (REST) and
  `frontend/src/api/sse.ts` (SSE). `localStorage` in the API client stores only presentation
  credentials/actor selection; it is not domain persistence.
* `frontend/src/lib/` contains pure presentation helpers and request-shaping/validation helpers
  for immediate form feedback (`setup.ts`, `workingDirectory.ts`, `mcpServers.ts`). These are
  intentionally duplicated *input ergonomics*, not authority: every setting, MCP specification,
  thread working directory, provider choice, and authorization decision is revalidated by backend
  schemas/services before persistence or execution. The backend remains authoritative.
* `frontend/electron/main.cjs` owns process/window lifecycle and health polling for the packaged
  backend. This is an intentionally retained shell exception required for desktop startup; it
  does not implement domain rules or persistence and the renderer remains API-only.
* No browser/native/CLI client currently performs provider calls, database access, filesystem
  access, subprocess execution, or agent orchestration. `scripts/check-client-boundaries.py` now
  protects `frontend/src` from accidental Node/runtime, direct integration, or client-persistence
  imports.

## Intentionally retained exceptions and risks

The Electron shell necessarily supervises a backend process, and browser `localStorage` contains
API credentials by design; neither is domain ownership. Static checks cannot prove that arbitrary
business rules have not been reimplemented as pure functions. Keep client helpers limited to
immediate feedback and display; add or extend a backend endpoint/service when a rule affects
authorization, persistence, routing, execution, or provider behavior.
