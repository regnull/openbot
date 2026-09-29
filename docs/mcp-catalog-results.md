# MCP catalog results — 2026-09-28

All 35 original IDs are retained. **12 fully identified initialize/tools-list passes; one additional protocol success with incomplete server identity (AWS); 22 blocked/unrun.** All six core candidates passed. Of the 15 originally declared credential-free entries, 12 returned initialize/tools-list successfully, but AWS reported an empty serverInfo.version and is classified blocked for identity completeness, not as a failed handshake. Linear needs authorization, Docker needs an isolated daemon, and DuckDB identity is unresolved. Context7 additionally passed without a key, with network denied. These are protocol checks, NOT a claim that every server works or that issue #205 is closed. No functional tool calls were made.

The [machine-readable matrix](mcp-catalog-results.json) contains exact versions, effective argv, environment, serverInfo/protocol, all tool names, timings, cleanup, artifact hashes and per-row provenance. The linked raw protocol logs preserve stdout/stderr and full JSON-RPC responses; only local root paths are symbolically normalized. Original raw log hashes remain in those files.

| ID | Package/version and metadata provenance | Catalog disposition | Initialize | tools/list | Specific evidence / limitation |
|---|---|---|---|---|---|
| filesystem | [@modelcontextprotocol/server-filesystem 2026.8.31](https://registry.npmjs.org/%40modelcontextprotocol%2Fserver-filesystem/latest); package metadata collected for isolated runtime staging | template | pass | pass (14) | [Protocol log](mcp-catalog-evidence/filesystem.json); initialize and tools/list only; no tools/call, public service, browser launch or account validation |
| git | [mcp-server-git 2026.8.18](https://pypi.org/pypi/mcp-server-git/json); package metadata collected for isolated runtime staging | template | pass | pass (12) | [Protocol log](mcp-catalog-evidence/git.json); initialize and tools/list only; no tools/call, public service, browser launch or account validation |
| memory | [@modelcontextprotocol/server-memory 2026.8.31](https://registry.npmjs.org/%40modelcontextprotocol%2Fserver-memory/latest); package metadata collected for isolated runtime staging | template | pass | pass (9) | [Protocol log](mcp-catalog-evidence/memory.json); initialize and tools/list only; no tools/call, public service, browser launch or account validation |
| sequential-thinking | [@modelcontextprotocol/server-sequential-thinking 2026.8.31](https://registry.npmjs.org/%40modelcontextprotocol%2Fserver-sequential-thinking/latest); package metadata collected for isolated runtime staging | template | pass | pass (1) | [Protocol log](mcp-catalog-evidence/sequential-thinking.json); initialize and tools/list only; no tools/call, public service, browser launch or account validation |
| time | [mcp-server-time 2026.8.18](https://pypi.org/pypi/mcp-server-time/json); package metadata collected for isolated runtime staging | template | pass | pass (2) | [Protocol log](mcp-catalog-evidence/time.json); initialize and tools/list only; no tools/call, public service, browser launch or account validation |
| fetch | [mcp-server-fetch 2026.8.18](https://pypi.org/pypi/mcp-server-fetch/json); package metadata collected for isolated runtime staging | template | pass | pass (1) | [Protocol log](mcp-catalog-evidence/fetch.json); initialize and tools/list only; no tools/call, public service, browser launch or account validation |
| github | [@modelcontextprotocol/server-github 2025.4.8](https://registry.npmjs.org/%40modelcontextprotocol%2Fserver-github); reused baseline registry snapshot: mcp-catalog-evidence/baseline-registry.json | deprecated | not run (blocked) | not run (blocked) | BLOCKED-DEPRECATED + CREDENTIALS: unsupported reference package; no GitHub access token used. |
| gitlab | [@modelcontextprotocol/server-gitlab 2025.4.25](https://registry.npmjs.org/%40modelcontextprotocol%2Fserver-gitlab); reused baseline registry snapshot: mcp-catalog-evidence/baseline-registry.json | deprecated | not run (blocked) | not run (blocked) | BLOCKED-DEPRECATED + CREDENTIALS/CONFIG: no GitLab token or test instance; API URL is configuration, not a secret. |
| postgres | [@modelcontextprotocol/server-postgres 0.6.2](https://registry.npmjs.org/%40modelcontextprotocol%2Fserver-postgres); reused baseline registry snapshot: mcp-catalog-evidence/baseline-registry.json | deprecated | not run (blocked) | not run (blocked) | BLOCKED-DEPRECATED + SERVICE-CONFIG: positional database URL missing in old entry; no safe automatic password-to-argv migration or DB fixture. |
| sqlite | [mcp-server-sqlite 2025.4.25](https://pypi.org/pypi/mcp-server-sqlite/json); package metadata collected for isolated runtime staging | deprecated | pass | pass (6) | [Protocol log](mcp-catalog-evidence/sqlite.json); MCP 2.2.0 fails Server.list_resources; --with mcp<2 tested using uv tool run with offline wheelhouse and SDK 1.30.0. Archived status retained. |
| puppeteer | [@modelcontextprotocol/server-puppeteer 2025.5.12](https://registry.npmjs.org/%40modelcontextprotocol%2Fserver-puppeteer/latest); package metadata collected for isolated runtime staging | deprecated | pass | pass (7) | [Protocol log](mcp-catalog-evidence/puppeteer.json); initialize and tools/list only; no tools/call, public service, browser launch or account validation |
| brave-search | [@modelcontextprotocol/server-brave-search 0.6.2](https://registry.npmjs.org/%40modelcontextprotocol%2Fserver-brave-search); reused baseline registry snapshot: mcp-catalog-evidence/baseline-registry.json | deprecated | not run (blocked) | not run (blocked) | BLOCKED-DEPRECATED + CREDENTIALS: no Brave key or provider calls. |
| slack | [@modelcontextprotocol/server-slack 2025.4.25](https://registry.npmjs.org/%40modelcontextprotocol%2Fserver-slack); reused baseline registry snapshot: mcp-catalog-evidence/baseline-registry.json | deprecated | not run (blocked) | not run (blocked) | BLOCKED-DEPRECATED + CREDENTIALS/CONFIG: no bot token/test workspace; team ID is configuration. |
| google-drive | [@modelcontextprotocol/server-gdrive 2025.1.14](https://registry.npmjs.org/%40modelcontextprotocol%2Fserver-gdrive); reused baseline registry snapshot: mcp-catalog-evidence/baseline-registry.json | deprecated | not run (blocked) | not run (blocked) | BLOCKED-DEPRECATED + CREDENTIALS: credential-file/account setup remains unvalidated; no Drive account exposed. |
| everart | [@modelcontextprotocol/server-everart 0.6.2](https://registry.npmjs.org/%40modelcontextprotocol%2Fserver-everart); reused baseline registry snapshot: mcp-catalog-evidence/baseline-registry.json | deprecated | not run (blocked) | not run (blocked) | BLOCKED-DEPRECATED + CREDENTIALS: no EverArt key; no image-generation calls. |
| serena | [serena-agent 1.7.0](https://pypi.org/pypi/serena-agent/json); package metadata collected for isolated runtime staging | template | pass | pass (29) | [Protocol log](mcp-catalog-evidence/serena.json); proxy_tools 0.1.0 source downloaded as inert data, hash checked, wheel built only inside sandbox; no source build on host. |
| context7 | [@upstash/context7-mcp 4.1.1](https://registry.npmjs.org/%40upstash%2Fcontext7-mcp/latest); package metadata collected for isolated runtime staging | template | pass | pass (2) | [Protocol log](mcp-catalog-evidence/context7.json); initialize and tools/list only; no tools/call, public service, browser launch or account validation |
| delimit | [delimit-cli 4.21.0](https://registry.npmjs.org/delimit-cli/latest); package metadata collected for isolated runtime staging | template | pass | pass (213) | [Protocol log](mcp-catalog-evidence/delimit.json); Launcher provisions its bundled Python server offline from staged wheels; no fake dependency marker or server stub. |
| playwright | [@playwright/mcp 0.0.82](https://registry.npmjs.org/%40playwright%2Fmcp/latest); package metadata collected for isolated runtime staging | template | pass | pass (25) | [Protocol log](mcp-catalog-evidence/playwright.json); initialize and tools/list only; no tools/call, public service, browser launch or account validation |
| notion | [@notionhq/notion-mcp-server 2.5.2](https://registry.npmjs.org/%40notionhq%2Fnotion-mcp-server); reused baseline registry snapshot: mcp-catalog-evidence/baseline-registry.json | deprecated | not run (blocked) | not run (blocked) | BLOCKED-UNSUPPORTED + CREDENTIALS: current local upstream explicitly unsupported; no Notion integration token/workspace used. |
| linear | [remote endpoint no verified version](https://linear.app/docs/mcp); source review / baseline unresolved identity; not a registry pass | template | not run (blocked) | not run (blocked) | Authenticated remote endpoint: OAuth/account or bearer token required per https://linear.app/docs/mcp (HTTP 200 source snapshot). No account authorization granted; endpoint not contacted. |
| sentry | [@sentry/mcp-server 0.42.0](https://registry.npmjs.org/%40sentry%2Fmcp-server); reused baseline registry snapshot: mcp-catalog-evidence/baseline-registry.json | template | not run (blocked) | not run (blocked) | CORRECTED-CONFIG / BLOCKED-CREDENTIALS: SENTRY_ACCESS_TOKEN documented; no token or optional paid LLM provider used. |
| stripe | [@stripe/mcp 0.3.3](https://registry.npmjs.org/%40stripe%2Fmcp); reused baseline registry snapshot: mcp-catalog-evidence/baseline-registry.json | unverified | not run (blocked) | not run (blocked) | BLOCKED-UNVERIFIED + CREDENTIALS: current root docs recommend remote OAuth; local launch setup not certified or silently migrated. No payments/API calls. |
| supabase | [@supabase/mcp-server-supabase 0.13.0](https://registry.npmjs.org/%40supabase%2Fmcp-server-supabase); reused baseline registry snapshot: mcp-catalog-evidence/baseline-registry.json | template | not run (blocked) | not run (blocked) | BLOCKED-CREDENTIALS/PROJECT: intended account/project/token setup not runtime-tested; no production database access. |
| vercel | [identity unresolved no verified version](https://github.com/vercel/mcp-adapter); source review / baseline unresolved identity; not a registry pass | unverified | not run (blocked) | not run (blocked) | BLOCKED-IDENTITY: npm namesake/source mismatch; executable suggestion removed, no automatic provider/transport substitution. |
| aws | [awslabs.aws-documentation-mcp-server 1.2.1](https://pypi.org/pypi/awslabs.aws-documentation-mcp-server/json); package metadata collected for isolated runtime staging | template | pass; identity incomplete | pass (5) | [Protocol log](mcp-catalog-evidence/aws.json); Protocol initialize and tools/list succeeded (5 tools), but AWS package 1.2.1 returned an empty serverInfo.version. The strict identity-completeness gate cannot accept this as a fully identified pass. Raw response is retained unchanged; no server version is invented and no functional request was made. |
| cloudflare | [@cloudflare/mcp-server-cloudflare 0.2.0](https://registry.npmjs.org/%40cloudflare%2Fmcp-server-cloudflare); reused baseline registry snapshot: mcp-catalog-evidence/baseline-registry.json | unverified | not run (blocked) | not run (blocked) | BLOCKED-UNVERIFIED + CREDENTIALS/CONFIG: current docs list multiple remote services; legacy token-only local default withheld, not automatically replaced. |
| mongodb | [@mongodb-js/mongodb-mcp-server 0.0.3](https://registry.npmjs.org/%40mongodb-js%2Fmongodb-mcp-server); reused baseline registry snapshot: mcp-catalog-evidence/baseline-registry.json | deprecated | not run (blocked) | not run (blocked) | BLOCKED-DEPRECATED/RENAMED + CREDENTIALS: replacement identity/configuration not migrated; legacy variable list not certified. |
| redis | [@modelcontextprotocol/server-redis 2025.4.25](https://registry.npmjs.org/%40modelcontextprotocol%2Fserver-redis); reused baseline registry snapshot: mcp-catalog-evidence/baseline-registry.json | deprecated | not run (blocked) | not run (blocked) | BLOCKED-DEPRECATED + SERVICE-CONFIG: no disposable Redis endpoint; credentials/account not necessarily paid. |
| duckdb | [identity unresolved no verified version](https://github.com/ktanaka101/duckdb_mcp_server); source review / baseline unresolved identity; not a registry pass | unverified | not run (blocked) | not run (blocked) | Original npm duckdb-mcp-server returned HTTP 404; advertised ktanaka101/duckdb_mcp_server also returned HTTP 404. Same-named PyPI distribution has placeholder repository URLs; no verified executable identity to run. |
| docker | [mcp-server-docker 0.3.0](https://pypi.org/pypi/mcp-server-docker/json); reused prior corrected identity metadata; not re-executed | template | not run (blocked) | not run (blocked) | Corrected ckreiling Python package 0.3.0 requires Docker Engine. No disposable daemon/socket is available inside the verified sandbox; /var/run/docker.sock is hidden by probe. Using the live host socket would violate isolation. No daemon or server launched. |
| tavily | [tavily-mcp 0.2.22](https://registry.npmjs.org/tavily-mcp); reused baseline registry snapshot: mcp-catalog-evidence/baseline-registry.json | template | not run (blocked) | not run (blocked) | BLOCKED-CREDENTIALS: no Tavily key or external search/extract calls; launch not runtime-tested. |
| firecrawl | [firecrawl-mcp 3.25.5](https://registry.npmjs.org/firecrawl-mcp); reused baseline registry snapshot: mcp-catalog-evidence/baseline-registry.json | template | not run (blocked) | not run (blocked) | BLOCKED-CREDENTIALS/RUNTIME: no Firecrawl key/crawl calls; Node >=22 in prior metadata, installed host runtime is not package execution evidence. |
| exa | [exa-mcp-server 3.4.1](https://registry.npmjs.org/exa-mcp-server); reused baseline registry snapshot: mcp-catalog-evidence/baseline-registry.json | template | not run (blocked) | not run (blocked) | BLOCKED-CREDENTIALS/RUNTIME: no Exa key/research calls; Node >=20 in prior metadata, launch not runtime-tested. |
| perplexity | [@perplexity-ai/mcp-server 1.3.0](https://registry.npmjs.org/%40perplexity-ai%2Fmcp-server/latest); reused prior corrected identity metadata; not re-executed | template | not run (blocked) | not run (blocked) | CORRECTED-IDENTITY / BLOCKED-CREDENTIALS: official scoped npm package documented; no Perplexity key or paid research calls. |

## What was actually exercised

Linux x86_64, system Python 3.12.3 and Node 22.23.3; exact distributions are in the JSON matrix. Python package versions can differ from initialize `serverInfo.version` (recorded verbatim). Entry points were run from exact staged packages, not repository-owned stubs. SQLite was additionally exercised through `uv tool run --with mcp<2` against the offline wheelhouse. This does not certify future unpinned latest resolutions or other operating systems.

Puppeteer and Playwright passed without browsers installed or launched; no navigation was attempted. Serena used a synthetic empty project directory; language-server provisioning, semantic operations and dashboard/browser behavior are not validated. Delimit exposed 213 tools, but none were invoked. Fetch, AWS and Context7 listed tools with all external traffic denied; public documentation retrieval remains untested. SQLite/Puppeteer protocol passes do not remove upstream archival/deprecation or make their catalog Add available.

SQLite first failed with `mcp==2.2.0`: `AttributeError: Server has no attribute list_resources`. Constraining its launcher to `--with mcp<2` resolved to 1.30.0 and returned six tools. Delimit initially failed offline dependency installation; after staging its exact fallback requirements, the unchanged launcher provisioned itself and passed. Serena initially lacked a proxy_tools wheel: its hash-checked 0.1.0 sdist was built inside the sandbox, then the dependency-complete package passed. Those are resolved staging/configuration failures, not invented passes.

## Isolation and preserved failures

Codex CLI 0.153.4 custom permissions denied the entire root except minimal runtime files, the disposable sandbox workspace and the CLI installation. Every run used `/usr/bin/env -i` with the allowlisted environment recorded in its receipt. Personal home, checkout, SSH agent directory and Docker socket were hidden. An outbound TCP attempt was denied. No real credentials, browser profile, production DB or public service were available to the server.

The first profile (`network.enabled=false`) also denied AF_UNIX socketpair sends and stalled Python asyncio. The repaired profile (`network.enabled=true`, `features.network_proxy=true`, no allowed domains) retained denied outbound TCP while allowing AF_UNIX wakeups. That setting alone is not evidence: the recorded boundary probes and actual Python handshakes establish this host-specific result. Systemd user sandbox properties were ineffective here and were not used. Never copy these settings without reproving the boundary on your host.

Retained failure logs: [SQLite SDK 2.2.0](mcp-catalog-evidence/sqlite-incompatible.json), [initial Git sandbox stall](mcp-catalog-evidence/git-initial-sandbox.json), [Delimit provisioning](mcp-catalog-evidence/delimit-initial.json). Registry baseline observations and primary-source URL/status/hash receipts are committed alongside these logs.

## Reproduce the project gates (no catalog server execution)

Use the repository's supported Python/uv and Node/pnpm versions with a fresh HOME,
no inherited provider credentials, and no real `.env` files in the checkout. Install
locked project dependencies with `uv sync --frozen` in backend and
`pnpm install --frozen-lockfile --ignore-scripts` in frontend (no Electron lifecycle download).
Do not run `make smoke`: those opt-in tests contact paid providers.

```sh
make test        # full backend, frontend and TypeScript check; excludes live smoke tests
make lint       # ruff, oxlint, renderer/backend boundary
make build      # TypeScript and production frontend build, no deploy
cd backend
uv run pytest -q tests/test_mcp_catalog.py tests/test_mcp_catalog_regressions.py tests/test_mcp_catalog_registry.py tests/test_mcp_catalog_probe.py tests/test_mcp_manager.py tests/test_mcp_db_config.py tests/test_mcp_config.py
cd ..
backend/.venv/bin/ruff check scripts/check-mcp-catalog.py scripts/probe-mcp-stdio.py
python3 scripts/check-mcp-catalog.py                 # entirely offline
python3 scripts/check-mcp-catalog.py --online --ids sqlite docker perplexity
```

The final command is an explicit metadata-only HTTPS check, not a server startup.
The default tests exercise synthetic protocol fixtures and OpenBot's repository-owned
stub as regressions; neither is counted as a catalog-server pass. They also validate
the committed matrix's 35 IDs, pass/blocked evidence, raw-log hashes and SQLite constraint.

## Reproduce a real protocol check (explicit opt-in)

1. Create a new disposable workspace outside your checkout/home data. Stage exactly
   the package versions recorded in the JSON. npm staging must use `--ignore-scripts
   --no-audit --no-fund`; Python staging must use `pip download --only-binary=:all:`
   without executing source metadata/build hooks on the host. Retain lockfiles and
   SHA-256 hashes. Build/install any source-only dependency inside the verified sandbox,
   never by relaxing these flags on the host. Serena requires such a build for
   `proxy_tools==0.1.0`. Delimit 4.21.0 additionally requires wheels for
   `fastmcp==3.2.4 pyyaml==6.0.3 pydantic==2.12.5 packaging==26.0` and their dependencies;
   expose them using `PIP_NO_INDEX=1` / `PIP_FIND_LINKS` inside its disposable HOME.
2. Establish an effective sandbox with a sanitized environment and no host home,
   project checkout, SSH/credential agents, live Docker socket or outbound network.
   Verify local AF_UNIX send/receive, denied outbound TCP, and denied private paths
   inside the exact launcher. Preserve that probe output. Deny all network domains;
   do not use the real OpenBot checkout as the sandbox workspace. A container name
   or claimed sandbox setting is not verification. The protocol recorder does NOT
   create or certify an OS sandbox.
3. The committed per-server receipts contain the exact tested `sandbox_launcher`,
   effective `launch_argv`, allowlisted environment and fixture substitutions.
   `$SANDBOX`, `$CODEX_HOME`, `$AUDIT` and `$PRIVATE_HOME` are path-normalization
   placeholders in evidence, not runnable shell variables auto-expanded by the client.
   Substitute only the independently verified local paths in a launch JSON:

   ```json
   {"argv": ["/absolute/path/to/verified-sandbox-launcher", "its-options", "--", "/path/inside/sandbox/to/server", "its-arguments"],
    "cwd": "/absolute/disposable/sandbox", "env": {"HOME": "/absolute/disposable/sandbox/home", "PATH": "/usr/bin:/bin"}}
   ```

   Use the recorded Codex permissions profile (if compatible with your host) or
   an equally verified disposable boundary. Execute package entry points inside
   that boundary, not with a bare `npx`/`uvx` on your host. Filesystem receives only
   the synthetic fixtures directory, memory gets a synthetic `MEMORY_FILE_PATH`,
   SQLite receives `--db-path` to a disposable DB, and Serena receives a synthetic Cwd.
   For SQLite use `uv tool run --no-index --find-links <wheelhouse> --with 'mcp<2'
   mcp-server-sqlite==2025.4.25 --db-path <fixture>` (SDK 1.30.0 in this run).
4. Run the stdlib recorder from the trusted checkout; its child is the sandbox
   launcher, not the unisolated third-party package:

   ```sh
   python3 scripts/probe-mcp-stdio.py --execute --launch-file /path/to/launch.json --output /path/to/new-receipt.json
   sha256sum /path/to/new-receipt.json
   ```

   It sends `initialize`, `notifications/initialized`, then paginated `tools/list`;
   no `tools/call`. JSON stdout must remain protocol-only. It records raw traffic,
   timing and cleanup, and fails on timeout, protocol errors, empty/duplicate tool
   lists or an incomplete cleanup. The 30-second protocol deadline is configurable.
   Output is created exclusively; use a fresh filename to preserve previous failures.
   The recorder itself was exercised against the real sandboxed Git package as well
   as synthetic success/pagination/error/timeout tests.
5. Compare identity, version, names/count and cleanup with the versioned receipt.
   A different version or fixture is a new result, not confirmation of this snapshot.
   Do not fill credentialed/OAuth/service rows with a metadata result or a local stub.
   Browser navigation, service operations and functional correctness remain separate
   explicitly authorized tests, not implied by initialize/tools-list.
