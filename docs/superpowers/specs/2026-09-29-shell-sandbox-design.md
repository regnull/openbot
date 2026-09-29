# Backend in Docker, shell as a separate user: design

Status: prototype, 2026-09-29. For #198. Per-command or per-thread containers (#145) are the
follow-up.

## Problem

`run_shell` runs `bash -lc` on the host as the server user. It inherits the server's environment
and can read anything that user can: `.env`, `secret.key`, the database (a bot's `sqlite3`
already corrupted it once, #195), and the rest of the home directory.

## What this does

The backend runs in a container (`Dockerfile`, `compose.yaml`). The UI stays on the host: either
the desktop app started with `--backend_url` (#202), which forwards `/api` from its main process
so no CORS change is needed, or `make frontend`, whose Vite proxy already points at `:8000`.

That alone keeps bots off the host's files, but not away from the backend's secrets. Running the
real image without the second user, a shell command runs as root, sees the provider key in its
environment, reads `OPENBOT_API_KEY` from the backend's `/proc/<pid>/environ` and lists `/data`.

So there is one small code change: with `SHELL_USER` set, `run_shell` starts commands as that user
(`shell`, uid 1001, in the image) with only PATH, HOME, USER, LOGNAME and LANG. Now the database,
`secret.key` and the backend's `/proc/<pid>/environ` all give "Permission denied", and the env has
no keys.

The shell user can still reach the API on localhost, so `SHELL_USER` needs `OPENBOT_API_KEY`: the
backend refuses to start without it, and so does compose. From the shell, `/api/v1/settings`
returns 401.

`SHELL_USER` is env only, not a Settings-page setting, so a bot can't turn it off through the API.
If the switch fails (unknown user, not root), the tool returns an error and never falls back to
running as the server user. Unset, nothing changes.

## Layout

- `/data` (volume, `0700`, root): database, `secret.key`, MCP files, logs. Provider keys saved on
  the settings page are stored encrypted in the database, so they are covered too.
- `/workspace` (bind mount of `./workspace`): group `workspace`, setgid, and the backend runs with
  umask 002, so the file tools and the shell user can edit each other's files.
- tini is PID 1. It passes the stop signal on to the backend and reaps what killed commands
  leave behind.
- compose sets the container paths explicitly, because a copied `.env` has host paths in it. The
  port is bound to localhost only, and `OPENBOT_PORT` changes it if 8000 is taken by `make dev`.

## Not covered

- The desktop app route. I used `make frontend` in a browser (setup, then a real bot running
  `run_shell`, which came back as `shell`). The app with `--backend_url` goes through the same
  `/api` forwarding, but I didn't have a packaged build to try it with.
- Network. The backend needs to reach the providers, so the shell can reach anything too. A
  container per thread with `--network none` (#145) or an egress proxy would be the next step.
- Threads whose working directory is outside `./workspace`: that path doesn't exist in the
  container.
- On Linux the entrypoint changes the group and mode of the host's `./workspace` (create it
  yourself first, or Docker makes it owned by root). I only ran this on macOS with Docker Desktop
  27.5.1, where the bind mount hides ownership.
- The image is about 1.9 GB, because it uses the full Python image so bots have git, curl and pip.
  A slim image with those installed would be smaller.
- `patch_file`, the file tools and MCP servers run as the backend (root, in the container). The
  file tools check paths before writing, but a process the shell user left running could still race
  them with a symlink. Running the whole backend as a non-root user would close that.
- The kernel is shared.

## Things I ran into

- The user switch goes through `setpriv`, not `Popen(user=...)`. uvicorn runs on uvloop, and
  uvloop's subprocess support rejects `user=` and `group=`. My first version passed its tests on
  plain asyncio and failed the moment a real bot called `run_shell`. setpriv also keeps the pid, so
  the process-group kill on timeout still works. `--no-new-privs` stops `su` and other setuid
  programs from getting back to root.
- Without an init process, a command that timed out with something still running in the
  background left a zombie. The kill worked, but the orphan went to PID 1, the backend, which never
  waits on it. That's why tini is in the image, and a test checks for zombies.
- Killing the Docker client doesn't stop the work: after `kill -9` on `docker run` the container
  keeps running, and the same goes for a command under `docker exec`. That matters for #145:
  timeouts there need `docker rm -f`, or `timeout` inside the container.
- Docker Desktop only shares `/Users`, `/Volumes`, `/private`, `/tmp` and `/var/folders`. A path
  outside them fails with "Mounts denied". A path that also exists in Docker's VM, like
  `/usr/share/doc`, gets mounted from the VM without any error.

## Tests

- Unit, no root or Docker: the user and the minimal env passed to the spawn, unchanged behaviour
  when unset, fail-closed for an unknown user and when the switch isn't allowed, and the API key
  requirement.
- `uv run pytest -m docker` (opt-in, like `smoke`): builds the image and checks the points above
  against a running container. That's 11 checks, about a minute after the first build.
