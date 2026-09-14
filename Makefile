.PHONY: dev backend frontend test build run lint setup

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

test:           ## run backend and frontend test suites
	cd backend && uv run pytest -q
	cd frontend && pnpm test && pnpm typecheck

lint:           ## lint backend (ruff) and frontend (oxlint)
	cd backend && uv run ruff check .
	cd frontend && pnpm lint

build:          ## build the frontend for production serving by the backend
	cd frontend && pnpm build

run: build      ## production-style single process on :8000 serving the built UI, from the repo root
	uv run --project backend uvicorn openbot.main:app --port 8000
