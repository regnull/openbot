# MCP servers in OpenBot: design

Status: agreed 2026-09-16, implemented 2026-09-17. Companion to `docs/architecture.md` §9 (tools).

## Goal

Let bots use tools from Model Context Protocol servers (Linear, Slack, GitHub, filesystem, anything
that speaks MCP) the way Claude Code does: a `mcpServers` config file, tools that appear in the
tool registry alongside the built-ins, and OAuth for remote servers that require it. Nothing about
the runner, per-bot tool selection, approvals or the output cap changes.

## Configuration

`MCP_CONFIG` (default `./mcp.json`), Claude Code's shape:

```json
{
  "mcpServers": {
    "github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"], "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"}},
    "linear": {"url": "https://mcp.linear.app/mcp"},
    "internal": {"url": "https://mcp.example.com/mcp", "headers": {"Authorization": "Bearer ${INTERNAL_KEY}"}}
  }
}
```

- `command` selects stdio; `url` selects streamable HTTP. `env`, `cwd`, `headers` are optional.
- `${VAR}` in `args`, `env`, `headers` and `url` expands from the server environment (`.env` is
  loaded there), so secrets never sit in the config file. An unset variable is an error for that
  server, not a silent empty string.
- A remote server with no static `Authorization` header uses OAuth when the server demands it.
- `enabled: false` keeps a server in the file but skips it.

Three related settings: `PUBLIC_URL` (default `http://127.0.0.1:8000`, used to build the OAuth
redirect URI), `MCP_TOKEN_KEY` (Fernet key for credentials at rest; auto-generated into
`MCP_TOKEN_KEY_FILE`, default `./mcp_token.key`, when unset).

## Lifecycle

`McpManager` (in `openbot/mcp/`) owns one entry per configured server:

| status | meaning |
|---|---|
| `connected` | session open, tools registered |
| `needs_auth` | remote server answered 401 and no stored credentials, or the user disconnected |
| `error` | failed to start or connect; `error` text kept |
| `disabled` | `enabled: false` in config |

At startup every enabled server is connected concurrently with a per-server timeout; failures are
recorded, never fatal to boot. Sessions are long-lived (one stdio process or HTTP session per
server for the life of the process) and torn down on shutdown. `reconnect(name)` tears down and
re-opens one server; the Settings UI exposes it.

Tools are loaded through `langchain-mcp-adapters`, renamed `<server>__<tool>` and registered into
the existing `ToolRegistry` with source `mcp:<server>`. Everything downstream is unchanged: bots
pick them by name, `approval_tools` gates them, `TOOL_OUTPUT_CAP` applies, the bot editor and the
Settings tools card list them. The registry gains `unregister(source)` so a disconnect removes them
and the runner's `resolve` drops names that are gone (it already warns rather than fails).

## OAuth

Per the MCP authorization spec (OAuth 2.1, PKCE, protected-resource metadata discovery, resource
indicator). The MCP SDK's `OAuthClientProvider` implements the whole flow as an `httpx` auth and
asks the application for three things:

1. **Token storage.** `mcp_credentials` table (migration 0009): `server` (PK), `client_info` and
   `tokens` as Fernet-encrypted JSON, `updated_at`. Client registration is stored so dynamic
   registration happens once.
2. **Redirect.** Instead of opening a browser, the manager records the authorization URL for that
   server under a pending flow keyed by the OAuth `state`, and the Settings UI opens it.
3. **Callback.** `GET /mcp/oauth/callback?code=&state=` (public, no API key: the browser arrives
   without one) resolves the pending flow's future; the SDK exchanges the code, stores tokens via
   (1), and the connection proceeds. The endpoint answers with a tiny page that returns the user to
   Settings.

`POST /api/v1/mcp/servers/{name}/connect` starts (or retries) the connection in the background and
returns `{authorization_url}` when the flow needs the user, `{status}` otherwise. Flows time out
after five minutes. `DELETE /api/v1/mcp/servers/{name}/credentials` forgets the tokens and returns
the server to `needs_auth`.

Client registration: dynamic registration by default. `client_metadata_url` (Client ID Metadata
Document) is passed through when `PUBLIC_URL` is public HTTPS, since the SDK supports it; not
otherwise exercised in v1. Pre-registered clients are out of scope for v1.

## Trust

MCP tools run with whatever credentials the server holds and are not path-confined. Whatever the
operator authorizes is shared by every bot given that tool: a bot calling Linear acts as the
operator. The per-tool approval flag is the control; the Settings card shows each server's status
and, where the server reports it, the connected account.

## API and UI

- `GET /api/v1/mcp/servers`: name, transport, status, error, tool names, `oauth` (bool), `account`.
- `POST /api/v1/mcp/servers/{name}/connect`, `DELETE /api/v1/mcp/servers/{name}/credentials`.
- `GET /mcp/oauth/callback` (public).
- Settings page: an "MCP servers" card listing each server with a status badge, tool count with
  the names on expand, and Connect / Reconnect / Disconnect buttons. Connect opens the
  authorization URL in a new tab and polls status until it changes.

## Tests

- Config: parsing, `${VAR}` expansion, unset variable error, transport detection, `enabled`.
- Manager: spawns a FastMCP stub over stdio, registers `stub__add` and `stub__echo`, tool call
  works, disconnect unregisters, a bad command yields `error` without failing others.
- OAuth: encrypted storage round-trip and key auto-generation; pending flow records the URL and the
  callback resolves it; a 401-only server lands in `needs_auth`.
- API: listing, connect returning an authorization URL from a fake pending flow, credentials delete.
- Frontend: status label helper.

## Hardening after review (same day)

- The browser flow may start only during an operator-initiated connect. At boot, on reconnect, and
  during a bot's tool call the SDK's redirect handler raises instead, so stored-but-revoked tokens
  land the server in `needs_auth` in seconds rather than holding the boot for five minutes, and a
  mid-run 401 comes back to the model as an `error:` result rather than parking the run.
- Sessions are swapped, not replaced: a reconnect opens the new session and registers its tools
  before retiring the old one, so runs never see a window without the server's tools. A session that
  dies on its own (child process exit, dropped connection) is noticed by its holder task: status
  `error`, tools unregistered.
- The tool wrapper invokes the adapter with a tool call so the server's `isError` surfaces as an
  `error:` result; binary content blocks become a placeholder; any exception becomes an `error:`
  result instead of failing the run.
- Credentials are bound to the server URL they were granted for (`resource_url`, migration 0010):
  re-pointing a config name at another host drops the old tokens instead of sending them there. An
  undecryptable row (rotated key) reads as "no credentials". A bad key errors that server, not the boot.
- Composed tool names are sanitised to `^[a-zA-Z0-9_-]{1,64}$`.
- Bots that list a tool of a configured-but-disconnected MCP server stay editable, and the runner
  advertises only tools that are actually registered.
- The public callback escapes everything the authorization server sends.

## Servers added from Settings (2026-09-17, follow-up)

Remote servers can be added in the UI, modelled on Claude's "Add custom connector" dialog: a
name and the HTTPS URL where the server accepts MCP requests (http only for localhost). They are
stored in `mcp_servers` (migration 0011) and merged with the file at startup; a database row whose
name collides with a file server is skipped, the file wins. `POST /api/v1/mcp/servers` stores the
server and connects it in the background; the listing carries `authorization_url` while the server
waits for the operator, and the Settings card opens it once. `DELETE /api/v1/mcp/servers/{name}`
removes a database server and forgets its credentials; file servers answer 409 and are edited in
`mcp.json`. The card labels file servers "mcp.json" and offers Remove only for database ones. Stdio
servers and servers that need a secret header stay file-only, so secrets never pass through the UI.

## Out of scope for v1

Editing servers' details from the browser, MCP resources and prompts, deferred tool loading (a
`search_tools` tool for very large servers), pre-registered OAuth clients, per-user identities.
