# Bot sandbox policies (NVIDIA/OpenShell pilot)

Policies for running OpenBot bots inside [NVIDIA/OpenShell](https://github.com/NVIDIA/OpenShell)
kernel-level sandboxes. Pilot scope: the `@engineer` bot, in **advisory** mode
(denials are logged and surfaced as drafted rule proposals, not hard failures).

## Contents

- `engineer.yaml` — policy for the `engineer` sandbox: workspace files, git remotes
  (github.com / api.github.com), package registries (pypi.org, files.pythonhosted.org),
  and uv's CPython release host. All network rules are `enforcement: audit` for the
  pilot; flip to `enforce` per rule before production.
- `engineer-base.Dockerfile` — sandbox image. The default sandbox image ships **without**
  git/gh/curl/python and apt is unusable inside (non-root, no network), so tools must be
  baked into the image before the sandbox starts.

## Quickstart (host)

```sh
# 1. Build the base image (gateway uses the local Docker daemon)
docker build -f policies/engineer-base.Dockerfile -t openshell/engineer-base:latest .

# 2. Create the sandbox (keep a sleep-style main process; create attaches to it)
openshell sandbox create engineer --from openshell/engineer-base:latest \
  -- sleep 100000   # detached: nohup openshell sandbox create engineer ...

# 3. Apply (or hot-reload) the policy — no restart needed
openshell policy set engineer --policy policies/engineer.yaml --wait

# 4. Run work inside
openshell sandbox exec engineer -- bash -c 'cd /sandbox && git …'

# 5. Audit + rule proposals
openshell logs engineer --source sandbox          # OCSF allow/deny events
openshell rule get engineer --status pending      # drafted rules from denials
```

## Hard-won details (v0.1.5)

- **Network `binaries` must be kernel-resolved real paths** (`readlink -f`), never
  symlinks. `git` fetch/push execs `/usr/lib/git-core/git-remote-http`; `pip` runs as the
  interpreter `/usr/bin/python3.12`. A symlink path fails silently as "connection refused";
  the sandbox log carries a `SYMLINK HINT` explaining it.
- **uv downloads CPython** builds from `github.com/astral-sh/...` releases
  (redirected via `releases.astral.sh`), so both hosts must be allowed for the uv binary —
  even when pypi itself is allowed.
- Policies hot-reload via `policy set --wait`; network rules are live fields.
- Default-deny holds: unlisted endpoints fail as connection refused.

## Pilot result (2026-10-23)

Full backend suite ran inside the sandbox: `uv sync --frozen`, ruff, pytest →
811 passed / 30 failed / 30 deselected. The 30 failures were environmental, not policy
denials: uv pulled Python 3.13 (repo targets 3.12) and the image lacked `patch` — both
fixed in the image/pinned-tooling follow-up. Audit log showed 36 denials, all default-deny
working as intended (e.g. `example.com`), plus the drafted rules listed by
`openshell rule get engineer --status pending`.
