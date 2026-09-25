.PHONY: dev backend frontend app electron electron-package test smoke build run lint setup reset_db sync_bots --include-llm-call-details

ELECTRON_DETAIL_ARGS := $(if $(filter --include-llm-call-details,$(MAKECMDGOALS)),--include-llm-call-details,)
ELECTRON_ROOT_ARGS := $(if $(ROOT_DIRECTORY),--root-directory "$(ROOT_DIRECTORY)",)

setup:          ## install backend and frontend dependencies, create .env from the template
	cd backend && uv sync
	cd frontend && pnpm install
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
	$(MAKE) electron

electron-package: ## Build a distributable Electron package (requires platform tooling)
	cd frontend && pnpm electron:package

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
