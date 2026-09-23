.PHONY: dev backend frontend app electron electron-package test smoke build run lint setup reset_db sync_bots

setup:          ## install backend and frontend dependencies, create .env from the template
	cd backend && uv sync
	cd frontend && pnpm install
	cp -n .env.example .env || true

dev:            ## run backend (8000) and frontend dev server (5173) together
	@$(MAKE) -j2 backend frontend

backend:        ## backend API with auto-reload, from the repo root so ./tools, ./workspace, .env resolve
	uv run --project backend uvicorn openbot.main:app --reload --port 8000

frontend:       ## Vite dev server, proxies /api to the backend
	cd frontend && pnpm dev

electron:       ## Electron desktop window against an already-running Vite dev server (start it with `make frontend`, and the backend with `make backend`)
	cd frontend && pnpm electron

app:            ## launch the OpenBot desktop application (auto-starts the Vite dev server; start the backend separately with `make backend`)
	@cd frontend && \
	( pnpm dev >/dev/null 2>&1 & echo $$! >.vite.pid ) && \
	trap 'kill $$(cat .vite.pid) 2>/dev/null; rm -f .vite.pid' EXIT && \
	until curl -s -o /dev/null http://localhost:5173; do sleep 0.2; done && \
	pnpm electron

electron-package: ## Build a distributable Electron package (requires platform tooling)
	cd frontend && pnpm electron:package

test:           ## run backend and frontend test suites (live provider smoke tests excluded)
	cd backend && uv run pytest -q
	cd frontend && pnpm test && pnpm typecheck

smoke:          ## run the live provider smoke tests -- these call real APIs and cost money
	cd backend && uv run pytest -m smoke -v

reset_db:       ## delete the local SQLite databases (app + LangGraph state); migrations and demo bots re-run on next start
	rm -f openbot.db openbot.db-* openbot.langgraph.db openbot.langgraph.db-*

sync_bots:      ## update the demo bots' instructions/tools/limits from the seed definitions (no threads or memories touched), from the repo root
	uv run --project backend python -m openbot.seed

lint:           ## lint backend (ruff) and frontend (oxlint)
	cd backend && uv run ruff check .
	cd frontend && pnpm lint

build:          ## build the frontend for production serving by the backend
	cd frontend && pnpm build

run: build      ## production-style single process on :8000 serving the built UI, from the repo root
	uv run --project backend uvicorn openbot.main:app --port 8000
