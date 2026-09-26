.PHONY: dev backend frontend app electron electron-release electron-package github-release test smoke build run lint setup reset_db sync_bots --include-llm-call-details

ELECTRON_DETAIL_ARGS := $(if $(filter --include-llm-call-details,$(MAKECMDGOALS)),--include-llm-call-details,)
ELECTRON_ROOT_ARGS := $(if $(strip $(ROOT_DIRECTORY)),--root-directory "$(ROOT_DIRECTORY)",)

# Resolves the Electron binary path and fails unless the file exists (require() alone only checks path.txt).
ELECTRON_PROBE := node -e "require('fs').accessSync(require('electron'))"

# pnpm 10 only runs the dependency lifecycle scripts allow-listed in frontend/pnpm-workspace.yaml.
# That list covers Electron's binary download, so the single `pnpm install` below also provisions
# the desktop app; the probe below turns a silently skipped download into a rebuild, then an error.
setup:          ## install backend, frontend and Electron dependencies, create .env from the template
	@command -v uv >/dev/null 2>&1 || { echo "uv is required (https://docs.astral.sh/uv/)" >&2; exit 1; }
	@command -v node >/dev/null 2>&1 || { echo "Node 24+ is required (https://nodejs.org/)" >&2; exit 1; }
	@command -v pnpm >/dev/null 2>&1 || { echo "pnpm 10+ is required (https://pnpm.io/installation)" >&2; exit 1; }
	cd backend && uv sync
	cd frontend && pnpm install
	@cd frontend && $(ELECTRON_PROBE) 2>/dev/null || { echo "Electron binary missing; re-running its download..."; pnpm rebuild electron; }
	@cd frontend && $(ELECTRON_PROBE) || { echo "Electron binary still missing; check frontend/pnpm-workspace.yaml allowBuilds and your network, then re-run make setup" >&2; exit 1; }
	cp -n .env.example .env || true

dev:            ## run backend (8000) and frontend dev server (5173) together
	@$(MAKE) -j2 backend frontend

backend:        ## backend API with auto-reload, from the repo root so ./tools, ./workspace, .env resolve
	uv run --project backend uvicorn openbot.main:app --reload --reload-dir backend/openbot --reload-dir tools --port 8000

frontend:       ## Vite dev server, proxies /api to the backend
	cd frontend && pnpm dev

electron:       ## launch Electron with a Vite frontend and dedicated backend on :8001 (override ELECTRON_BACKEND_PORT)
	./scripts/electron-dev.sh $(ELECTRON_DETAIL_ARGS) $(ELECTRON_ROOT_ARGS)

app:            ## alias for `make electron`; starts the Electron frontend and backend together
	$(MAKE) electron ELECTRON_DETAIL_ARGS="$(ELECTRON_DETAIL_ARGS)"

electron-release: ## Build a host-platform Electron release under frontend/release/, versioned <next>-dev
	@command -v node >/dev/null 2>&1 || { echo "Node 24+ is required (https://nodejs.org/)" >&2; exit 1; }
	@command -v pnpm >/dev/null 2>&1 || { echo "pnpm 10+ is required (https://pnpm.io/installation)" >&2; exit 1; }
	cd frontend && pnpm electron:package "-c.extraMetadata.version=$$(node scripts/version.cjs --dev)"

github-release: ## build macOS + Linux apps from HEAD and publish them as the next vX.Y.N GitHub release (DRY_RUN=1 to skip publishing)
	DRY_RUN="$(DRY_RUN)" ./scripts/github-release.sh

# Backward-compatible name retained for existing packaging workflows.
electron-package: electron-release

test:           ## run backend and frontend test suites (live provider smoke tests excluded)
	cd backend && uv run pytest -q
	cd frontend && pnpm test && pnpm typecheck

smoke:          ## run the live provider smoke tests -- these call real APIs and cost money
	cd backend && uv run pytest -m smoke -v

reset_db:       ## delete the local SQLite databases (app + LangGraph state); migrations and demo bots re-run on next start
	rm -f .openbot/openbot.db .openbot/openbot.db-* .openbot/openbot.langgraph.db .openbot/openbot.langgraph.db-*

sync_bots:      ## update the demo bots' instructions/tools/limits from the seed definitions (no threads or memories touched), from the repo root
	uv run --project backend python -m openbot.seed

lint:           ## lint backend (ruff), frontend (oxlint), and enforce the renderer/backend boundary
	cd backend && uv run ruff check .
	cd frontend && pnpm lint
	python3 scripts/check-client-boundaries.py

build:          ## build the frontend for production serving by the backend
	cd frontend && pnpm build

run: build      ## production-style single process on :8000 serving the built UI, from the repo root
	uv run --project backend python -m openbot.cli --port 8000
