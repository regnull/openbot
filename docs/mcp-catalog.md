# MCP catalog

OpenBot's Settings catalog retains the original 35 entries. Metadata lives in
`backend/openbot/mcp/catalog.py`. Package resolution is not a trust decision or
evidence that a server initializes, lists tools, or performs tool calls correctly.
No third-party catalog server is certified for general use by these tests.
The versioned [35-entry results matrix](mcp-catalog-results.md) records actual
isolated initialize/tools-list checks separately from untested functional calls.

## What Settings offers

- `template`: a command or remote endpoint that can be added **disabled**. This
  does not install a package, connect, or claim the configuration is ready.
- `deprecated`: unavailable for catalog Add because the package is deprecated,
  archived, or explicitly unsupported upstream. Details retain its identity and
  explain why it is withheld; this is not an observed protocol failure.
- `unverified`: unavailable for catalog Add because identity or launch setup is
  unresolved. Do not substitute a same-named package from another registry.

The API rejects Add for the latter two statuses with HTTP 422, even if a client
bypasses Settings. All 35 entries remain visible. Custom server configuration
remains available to operators; this is not a global runtime ban or a sandbox.
The catalog does not alter existing stored configurations.

**Enable starts a connection automatically.** Editing an already-enabled server
also reconnects it; startup connects enabled stored servers. A later Connect click
is not a second execution barrier. Review configuration while disabled, then grant
the resulting tools to bots explicitly. Commands run with the user's privileges.

## Corrected identities and setup (2026-09-28 metadata review)

| Entry | Correction / disposition |
| --- | --- |
| Git, Time, Fetch | Use `uvx mcp-server-git`, `uvx mcp-server-time`, and `uvx mcp-server-fetch`. The former scoped npm names do not exist. Upstream Python manifests declare those console scripts. |
| SQLite | Python `uvx --with 'mcp<2' mcp-server-sqlite --db-path <explicit-disposable-path>`, not npm or a bare positional path. Real startup with SDK 2.2.0 failed (`Server.list_resources` missing); SDK 1.30.0 passed initialize and listed six tools. Archived upstream: Add remains unavailable. The template uses `${OPENBOT_MCP_SQLITE_DB}` rather than writing a default DB in the working directory. |
| Docker | `uvx mcp-server-docker` matches ckreiling's advertised Python project; the npm namesake advertises a different repository. Requires Python >=3.12 and privileged Docker access. This correction does not certify runtime compatibility. |
| Perplexity | Official `npx -y @perplexity-ai/mcp-server`, not `perplexity-mcp` from a different project. Requires `PERPLEXITY_API_KEY`. |
| DuckDB | npm package and advertised source unavailable in the review. Same-name PyPI project identity unresolved. No launch command offered. |
| Vercel | Configured npm package belongs to a different project; advertised Vercel source is an HTTP framework adapter, not that CLI. No launch command offered; no silent switch to another service. |
| Filesystem | Explicit allowed-directory argument required: replace `${OPENBOT_MCP_ALLOWED_DIR}` in Args with a reviewed path before enabling. OpenBot does not supply client roots. Missing process variable fails configuration before launch. |
| PostgreSQL | Archived CLI expects a positional URL, not `DATABASE_URL` in Env. Add unavailable. No automatic password-to-Args workaround: Args are not encrypted. |
| Linear | Remote authenticated service at `/mcp`, not an anonymous/no-credentials candidate. OAuth account authorization or a configured bearer Authorization header is required. |
| AWS | This is **AWS Documentation**, for public documentation; it is not private-resource administration and does not require AWS keys. |
| Sentry | Upstream stdio configuration uses `SENTRY_ACCESS_TOKEN`. AI-powered search needs a separately configured LLM provider; no provider is enabled by this catalog. |
| Context7 | An API key may be optional depending on the plan. An empty required-credentials list does not promise anonymous operation. |
| Serena | Preserve `uvx --from serena-agent serena start-mcp-server --project-from-cwd`; explicitly select Cwd before enabling. |

Deprecated npm entries withheld: GitHub, GitLab, PostgreSQL, Puppeteer, Brave
Search, Slack, Google Drive, EverArt, MongoDB, Redis. MongoDB's npm deprecation
points to a renamed package, but its configuration/runtime have not been migrated.
SQLite is archived; Notion's current upstream README explicitly says its local
implementation is no longer actively maintained or supported. Stripe and
Cloudflare's current upstream READMEs describe remote services rather than the
catalog's local defaults; those local configurations are marked unverified and
withheld pending explicit review, not declared proven failures.

Upstream evidence: [reference servers](https://github.com/modelcontextprotocol/servers),
[archived servers](https://github.com/modelcontextprotocol/servers-archived),
[Docker](https://github.com/ckreiling/mcp-server-docker),
[Perplexity](https://github.com/perplexityai/modelcontextprotocol),
[Linear authentication](https://linear.app/docs/mcp),
[AWS Documentation](https://github.com/awslabs/mcp/tree/main/src/aws-documentation-mcp-server),
[Sentry](https://github.com/getsentry/sentry-mcp),
[Notion](https://github.com/makenotion/notion-mcp-server),
[Stripe](https://github.com/stripe/agent-toolkit),
[Cloudflare](https://github.com/cloudflare/mcp-server-cloudflare).

## Existing installs: edit or re-add explicitly

Catalog updates affect **new Add operations only**. The database is the runtime
source of truth; importing `mcp.json` is one-time by name, not a migration.

1. Disable the existing server in Settings before editing. Do not merely disconnect
   an enabled server: startup or later edits may reconnect it.
2. Review the updated catalog details. For supported templates, edit Command and
   Args to the corrected values above, select Cwd/allowed directories, and review
   Env or Headers. `${VAR}` expansion reads OpenBot's process environment, **not**
   the server's Env map. In the UI, replacing a path placeholder directly in Args
   is usually simpler; quote paths containing spaces.
3. Keep secrets in Env or Headers, never literal command arguments. Credential
   names in the catalog are descriptive, not automatically populated or enforced.
4. Alternatively remove the old entry and add the updated template disabled.
   Removal also forgets its stored credentials; re-enter them through Settings.
   Re-adding unavailable entries is intentionally blocked. Do not migrate them
   to namesakes or new transports without reviewing the selected replacement.
5. Only enable after reviewing privileges, setup, authentication and package
   provenance. Enabling may download and execute third-party dependencies.

## Tests and opt-in registry checks

`make test` runs offline catalog identity/configuration/API/UI regressions plus
the repository-owned MCP stub integration tests. The stub demonstrates OpenBot's
initialize/tools-list/tool-call path, **not** health of any catalog server.

`python3 scripts/check-mcp-catalog.py` prints the registry identities without
network access. To check specific public registry metadata explicitly:

```sh
python3 scripts/check-mcp-catalog.py --online --ids git time fetch sqlite docker perplexity
```

Omit `--ids` to check all catalog packages. The checker only GETs npm/PyPI JSON;
it does not install packages, download archives, run binaries, contact remote MCP
endpoints, or accept credentials. It handles Serena's `--from` distribution and
AWS's `@latest` form and SQLite's `--with` constraint, checks returned name/version and npm bin metadata, reports
engine/Python requirements and deprecation, and compares repository declarations.
HTTP 404, other HTTP/network errors, missing executables, deprecation and missing
or mismatched repository declarations are separate outcomes. Redirected/archived
repositories require manual upstream review. PyPI JSON cannot prove a console
script exists inside the actual distribution.

Exit 1 means an invalid configuration/metadata response or registry request failure;
exit 0 only means that the report was collected without those errors. It may still
contain deprecated, unavailable, or needs-source-review rows. Neither exit status
certifies server health. Registry checks are deliberately not part of default CI:
upstream mutation/outages should not turn an offline regression suite into a
package execution job. All default tests use local/synthetic data.

## Runtime evidence and remaining limits

Keep package metadata, configuration review, initialize, tools/list and functional
tools/call as separate stages. Missing credentials, OAuth, service fixtures,
browser setup or safe isolation are **not tested / blocked**, not passes and not
inferred handshake failures. Even credential-free startup runs third-party code.
Use a vetted disposable nonprivileged environment without personal home, real
keys, logged-in browser, production DB, Docker socket or private network access.
Record exact approved package/version, effective fixture argv, initialize result,
paginated tool list, errors and cleanup before making per-entry runtime claims.
Mutable latest packages and declarations are not an artifact-integrity audit.
