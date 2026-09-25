# Contributing to OpenBot

Thanks for helping. Keep changes small and focused.

## Setup

Prerequisites: Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node 24+ with [pnpm](https://pnpm.io/) 10.

```bash
make setup   # backend deps, frontend deps, .env from template
make test    # backend pytest + frontend tests/typecheck
make lint    # ruff, frontend lint, client-boundary check
```

Day-to-day: `make dev` (API on :8000, UI on :5173). Optional desktop: `make app`.

## Pull requests

1. Fork (or branch from `main` if you have write access).
2. Make a focused change — one concern per PR.
3. Run `make test` and `make lint` locally; fix failures before opening the PR.
4. Open a PR against `main` with a short description of what and why.
5. Prefer tests for behavior changes. Docs-only PRs are welcome.

## Expectations

- **Tests**: add or update coverage when you change behavior.
- **Lint**: keep `make lint` clean.
- **Scope**: small, reviewable PRs beat large mixed ones.
- **Security**: OpenBot runs with host privileges (`run_shell` is unsandboxed). Do not weaken trust boundaries without discussion.

Questions? Open an issue. Look for `good-first-issue` and `help-wanted` labels.
