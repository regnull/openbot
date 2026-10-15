# Unused-code audit

**Scope:** `backend/openbot`, `backend/tests`, `frontend/src`, and project dependency declarations at `backend/pyproject.toml` and `frontend/package.json`.

## Summary

No high-confidence unused imports or local variables were found. Ruff's unused-code rules passed for all backend production and test Python code, and TypeScript compilation passed. The frontend linter reported six warnings, but they are React/compiler-style warnings rather than unused code. No source code was changed by this audit.

## Findings

### Medium confidence — frontend lint warnings (not unused code)

- `frontend/src/pages/ThreadPage.tsx:35` and `:47`: `setState`/`setHasMore` are called synchronously from effects. These effects reset state when the route id changes and hydrate fetched data; both values are consumed by the component. This is intentional synchronization and not dead code. Consider refactoring only if React Compiler guidance becomes a project requirement.
- `frontend/src/pages/BotEditorPage.tsx:37`: `setForm` is called from an effect after bot data arrives. The form state is subsequently used by the editor, so it is live. The warning is a state-in-effect style issue, not an unused variable.
- `frontend/src/pages/ThreadPage.test.tsx:68-69`: the test stores router hooks in refs so the test can drive navigation and inspect location. The assignments are deliberate test instrumentation.
- `frontend/src/components/RunCard.tsx:15`: exported `usageLabel` triggers the `only-export-components` Fast Refresh warning. It is imported by `frontend/src/lib/threadUsageLabel.test.ts` and is intentionally exported for testing/reuse; it is not unused.

### Low confidence — intentionally empty/abstract code

- `backend/openbot/db/models.py:68`: an empty declarative/model class body (`pass`) is structurally required by the ORM model definition.
- `backend/openbot/mcp/config.py:49`: an empty configuration/model class body (`pass`) is a valid marker/schema class.
- `backend/openbot/runtime/actors.py:74`: `NotImplementedError` marks an abstract/extension operation and is reachable if an implementation fails to override it.
- `backend/openbot/runtime/bus.py:44,53` and `backend/openbot/tools/builtin/shell.py:15`: empty exception-handling or callback bodies are intentional control flow, not unreachable unused code.

## Checks and tools

- `ruff check openbot tests` — passed.
- `ruff check --select F401,F841 openbot tests` — passed; no unused Python imports or assigned-but-never-used locals.
- `pnpm exec oxlint src` — 0 errors, 6 warnings listed above.
- `pnpm exec tsc -b --pretty false` — passed.
- Frontend Vitest — 23 files, 94 tests passed.
- Backend pytest was not runnable in the available checkout because the expected `backend/.venv/bin/pytest` executable was unavailable at the time of the audit. (The repository's backend virtualenv contains Ruff but not pytest.)

## Limitations and recommendations

No dedicated whole-program dead-code/dependency analyzer (`vulture`, `deptry`, `ts-prune`, or equivalent) is installed. Static reachability across FastAPI route discovery, ORM metadata, plugin/tool registration, migrations, and public exports cannot be proven by grep alone. Dependency declarations were therefore not removed: each may be loaded indirectly by framework/plugin configuration or runtime imports. For higher confidence, run a dedicated dependency/dead-code tool in CI with framework entry points configured, then review its candidates manually.

Recommended cleanup is optional: split `usageLabel` into a non-component utility module to silence the Fast Refresh warning, and consider later refactoring state-reset effects if the React Compiler warnings become enforced. Neither is an unused-code finding.

_OpenBot - @engineer_
