# macOS desktop application

## Build and install

On macOS, install dependencies and build the signed/unsigned artifacts:

```bash
make setup
make electron-package
open frontend/release/OpenBot-0.0.0-arm64.dmg
```

Drag `OpenBot.app` to `/Applications`. The exact artifact name includes the app version and architecture; the ZIP in the same directory is an alternative distribution.

The packaged app loads the Vite build from `file://`, starts the bundled backend resource on `127.0.0.1:8000`, waits for `/api/v1/health`, then creates the window. Backend data is kept in macOS Application Support. On quit, Electron sends SIGTERM to the backend process group.

The backend resource is launched with `uv`; therefore users must have `uv` installed and available on PATH. A future release can replace `scripts/electron-backend.sh` with a frozen Python executable without changing the Electron packaging contract.

## Development

```bash
make app       # backend :8001 + Vite + Electron, with cleanup on Ctrl-C
```

Browser workflows (`make dev`, `make run`) remain unchanged. `OPENBOT_URL` selects a remote deployment; `OPENBOT_API_URL` can override its API origin.

## Signing and notarization

Local builds are unsigned and not notarized unless electron-builder signing/notarization credentials are configured (`CSC_LINK`, `CSC_KEY_PASSWORD`, and Apple notarization settings). Gatekeeper may require right-clicking the locally built app and choosing **Open**. Build on macOS for a native `.app`/DMG; cross-platform packaging is not a substitute for macOS validation.
