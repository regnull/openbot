# OpenBot frontend

The React and TypeScript UI runs in the browser through Vite or inside the optional Electron app. It talks to the backend over HTTP and server-sent events.

## Layout

- `src/pages/`: route-level screens for bots, threads, inbox, settings, and schedules.
- `src/components/`: shared UI, including the controls and status primitives in `ui.tsx`.
- `src/api/`: backend client, event stream, and API types.
- `src/lib/`: client-side state and helpers. `src/index.css` defines semantic theme tokens used by components.
- `electron/`: desktop main process (`main.cjs`), preload bridge (`preload.cjs`), and packaged `app://openbot` scheme (`scheme.cjs`).

## Develop and check

From the repository root, run `make setup` once, then `make dev` to start the API on port 8000 and Vite on port 5173. For the desktop app, see [Desktop app (Electron)](../README.md#desktop-app-electron).

From `frontend/`, run:

```sh
pnpm test
pnpm lint
pnpm typecheck
```

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full project checks and PR process.
