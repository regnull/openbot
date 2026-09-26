# macOS desktop application

## Build and install

On macOS, install dependencies and build the signed/unsigned artifacts:

```bash
make setup
make electron-package
open frontend/release/OpenBot-0.0.0-arm64.dmg
```

Drag `OpenBot.app` to `/Applications`. The exact artifact name includes the app version and architecture; the ZIP in the same directory is an alternative distribution.

The packaged app loads the Vite build from `file://` and starts the bundled backend resource on `127.0.0.1:8000`. The window opens right away with a local "Starting OpenBot…" page (`frontend/electron/loading.html`) and switches to the app once `/api/v1/health` answers. If the app URL fails to load (for example Vite is not running in development, or `OPENBOT_URL` is unreachable), the window shows "Can't reach OpenBot" and retries every few seconds instead of staying blank. Backend data is kept in macOS Application Support. On quit, Electron sends SIGTERM to the backend process group.

The backend resource is launched with `uv`; therefore users must have `uv` installed and available on PATH. A future release can replace `scripts/electron-backend.sh` with a frozen Python executable without changing the Electron packaging contract.

## Development

```bash
make app       # backend :8001 + Vite + Electron, with cleanup on Ctrl-C
```

To check the status page, start Electron with `OPENBOT_URL` pointing at a port with nothing on it (for example `OPENBOT_URL=http://127.0.0.1:5999 pnpm --dir frontend electron`): the window shows the retry message, and loads the UI once something serves that URL.

Browser workflows (`make dev`, `make run`) remain unchanged. `OPENBOT_URL` selects a remote deployment; `OPENBOT_API_URL` can override its API origin.

## Signing and notarization

Local builds are unsigned and not notarized unless electron-builder signing/notarization credentials are configured (`CSC_LINK`, `CSC_KEY_PASSWORD`, and Apple notarization settings). Gatekeeper may require right-clicking the locally built app and choosing **Open**. Build on macOS for a native `.app`/DMG; cross-platform packaging is not a substitute for macOS validation.
