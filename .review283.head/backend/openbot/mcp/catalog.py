"""Curated, opt-in MCP server catalog.

Entries are metadata for opt-in servers (stdio or remote HTTP); installing an entry stores it disabled so
OpenBot never executes a newly discovered third-party server without an explicit user action.
Package metadata and upstream documentation are not evidence of a successful MCP connection.
"""
from __future__ import annotations

from typing import Literal, TypedDict


class CatalogEntry(TypedDict):
    id: str
    name: str
    description: str
    provider: str
    source_url: str
    transport: str                           # "stdio" | "http"
    command: str                             # empty for remote or unresolved identities
    args: list[str]                          # empty for remote or unresolved identities
    url: str                                 # empty string for stdio entries
    required_credentials: list[str]
    compatibility: list[str]
    status: Literal["template", "deprecated", "unverified"]
    status_reason: str


def _npm(id: str, name: str, description: str, package: str, provider: str, source_url: str,
         credentials: list[str] | None = None, args: list[str] | None = None,
         compatibility: list[str] | None = None) -> CatalogEntry:
    return {"id": id, "name": name, "description": description, "provider": provider,
            "source_url": source_url, "transport": "stdio", "command": "npx",
            "args": ["-y", package, *(args or [])], "url": "",
            "required_credentials": credentials or [],
            "compatibility": compatibility or ["Requires Node.js and npx"],
            "status": "template", "status_reason": "Not runtime-certified; see versioned test results and review configuration before enabling."}


def _uvx(id: str, name: str, description: str, package: str, provider: str, source_url: str,
         credentials: list[str] | None = None, args: list[str] | None = None,
         compatibility: list[str] | None = None, with_packages: list[str] | None = None) -> CatalogEntry:
    return {"id": id, "name": name, "description": description, "provider": provider,
            "source_url": source_url, "transport": "stdio", "command": "uvx",
            "args": [*[arg for dep in (with_packages or []) for arg in ("--with", dep)], package, *(args or [])], "url": "",
            "required_credentials": credentials or [],
            "compatibility": compatibility or ["Requires uv and Python"],
            "status": "template", "status_reason": "Not runtime-certified; see versioned test results and review configuration before enabling."}


def _remote(id: str, name: str, description: str, url: str, provider: str, source_url: str,
            credentials: list[str] | None = None,
            compatibility: list[str] | None = None) -> CatalogEntry:
    return {"id": id, "name": name, "description": description, "provider": provider,
            "source_url": source_url, "transport": "http", "command": "",
            "args": [], "url": url,
            "required_credentials": credentials or [],
            "compatibility": compatibility or ["Remote server – no local runtime required"],
            "status": "template", "status_reason": "Runtime not tested; review authentication before enabling."}


CATALOG: tuple[CatalogEntry, ...] = (
    _npm("filesystem", "Filesystem", "Read, write, search, and manage files in explicitly allowed directories.", "@modelcontextprotocol/server-filesystem", "MCP steering group", "https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem", args=["${OPENBOT_MCP_ALLOWED_DIR}"], compatibility=["Requires Node.js and npx. Before enabling, replace ${OPENBOT_MCP_ALLOWED_DIR} in Args with an explicit allowed directory; never default to your home or project root. Alternatively set it in OpenBot's process environment (not the server Env editor)."]),
    _uvx("git", "Git", "Inspect and manipulate local Git repositories.", "mcp-server-git", "MCP steering group", "https://github.com/modelcontextprotocol/servers/tree/main/src/git", compatibility=["Requires uv, Python, and Git; review repository access before enabling"]),
    _npm("memory", "Memory", "Persist entities and relations in a local knowledge graph.", "@modelcontextprotocol/server-memory", "MCP steering group", "https://github.com/modelcontextprotocol/servers/tree/main/src/memory"),
    _npm("sequential-thinking", "Sequential Thinking", "Break complex problems into explicit reasoning steps.", "@modelcontextprotocol/server-sequential-thinking", "MCP steering group", "https://github.com/modelcontextprotocol/servers/tree/main/src/sequentialthinking"),
    _uvx("time", "Time", "Time and timezone conversion utilities.", "mcp-server-time", "MCP steering group", "https://github.com/modelcontextprotocol/servers/tree/main/src/time"),
    _uvx("fetch", "Fetch", "Fetch web pages and return readable content.", "mcp-server-fetch", "MCP steering group", "https://github.com/modelcontextprotocol/servers/tree/main/src/fetch"),
    _npm("github", "GitHub", "Search repositories and manage issues, pull requests, and files.", "@modelcontextprotocol/server-github", "MCP steering group", "https://github.com/modelcontextprotocol/servers/tree/main/src/github", ["GITHUB_PERSONAL_ACCESS_TOKEN"]),
    _npm("gitlab", "GitLab", "Work with GitLab projects, issues, and merge requests.", "@modelcontextprotocol/server-gitlab", "MCP steering group", "https://github.com/modelcontextprotocol/servers/tree/main/src/gitlab", ["GITLAB_PERSONAL_ACCESS_TOKEN", "GITLAB_API_URL"]),
    _npm("postgres", "PostgreSQL", "Inspect schemas and run PostgreSQL queries.", "@modelcontextprotocol/server-postgres", "MCP steering group", "https://github.com/modelcontextprotocol/servers-archived/tree/main/src/postgres", compatibility=["Archived CLI requires a positional database URL, not DATABASE_URL in Env. No runnable default is offered: Args are not encrypted and a URL may expose a password. Use a maintained server with secure configuration instead."]),
    _uvx("sqlite", "SQLite", "Query and update SQLite databases.", "mcp-server-sqlite", "MCP steering group", "https://github.com/modelcontextprotocol/servers-archived/tree/main/src/sqlite", args=["--db-path", "${OPENBOT_MCP_SQLITE_DB}"], with_packages=["mcp<2"], compatibility=["Archived Python server; requires uv and Python. MCP SDK 2.x breaks startup; --with mcp<2 retains the tested 1.x API. Use --db-path followed by an explicit disposable database path, not a bare path. No default database in the working directory is selected."]),
    _npm("puppeteer", "Puppeteer", "Automate a Chromium browser and capture pages.", "@modelcontextprotocol/server-puppeteer", "MCP steering group", "https://github.com/modelcontextprotocol/servers/tree/main/src/puppeteer", compatibility=["Requires a compatible Chromium installation"]),
    _npm("brave-search", "Brave Search", "Search the web using the Brave Search API.", "@modelcontextprotocol/server-brave-search", "MCP steering group", "https://github.com/modelcontextprotocol/servers/tree/main/src/brave-search", ["BRAVE_API_KEY"]),
    _npm("slack", "Slack", "Search conversations and interact with Slack workspaces.", "@modelcontextprotocol/server-slack", "MCP steering group", "https://github.com/modelcontextprotocol/servers/tree/main/src/slack", ["SLACK_BOT_TOKEN", "SLACK_TEAM_ID"]),
    _npm("google-drive", "Google Drive", "Search and read files in Google Drive.", "@modelcontextprotocol/server-gdrive", "MCP steering group", "https://github.com/modelcontextprotocol/servers/tree/main/src/gdrive", ["GOOGLE_APPLICATION_CREDENTIALS"]),
    _npm("everart", "EverArt", "Generate images through EverArt models.", "@modelcontextprotocol/server-everart", "EverArt", "https://github.com/modelcontextprotocol/servers/tree/main/src/everart", ["EVERART_API_KEY"]),
    {"id": "serena", "name": "Serena", "description": "Semantic code navigation, editing, and project memories for software agents.", "provider": "Oraios", "source_url": "https://github.com/oraios/serena", "transport": "stdio", "command": "uvx", "args": ["--from", "serena-agent", "serena", "start-mcp-server", "--project-from-cwd"], "url": "", "required_credentials": [], "compatibility": ["Requires uv; the upstream package exposes the serena executable. Set Cwd to the intended project before enabling; --project-from-cwd uses that directory."], "status": "template", "status_reason": "Not runtime-certified; see versioned test results and review project access before enabling."},
    _npm("context7", "Context7", "Retrieve current, version-specific library documentation for coding tasks.", "@upstash/context7-mcp", "Upstash", "https://github.com/upstash/context7", compatibility=["Requires Node.js and npx; CONTEXT7_API_KEY may be optional depending on the Context7 plan. External documentation service; authentication/configuration not runtime-tested."]),
    _npm("delimit", "Delimit", "Keep decisions, tasks, and handoffs on the local machine across AI coding assistants; merge gate for AI-written code.", "delimit-cli", "Delimit", "https://github.com/delimit-ai/delimit-mcp-server", args=["mcp"], compatibility=["Requires Node.js, npx, and Python 3.9+; the first run creates a virtualenv under ~/.delimit and installs the server's Python dependencies"]),
    _npm("playwright", "Playwright", "Browser automation using Playwright.", "@playwright/mcp", "Microsoft", "https://github.com/microsoft/playwright-mcp", compatibility=["Requires browser binaries; run the package's browser install step"]),
    _npm("notion", "Notion", "Search and update Notion pages and databases.", "@notionhq/notion-mcp-server", "Notion", "https://github.com/makenotion/notion-mcp-server", ["NOTION_TOKEN"]),
    _remote("linear", "Linear", "Read and manage Linear issues, projects, and cycles.", "https://mcp.linear.app/mcp", "Linear", "https://linear.app/docs/mcp", ["Linear account authorization (OAuth or bearer token)"], compatibility=["Remote authenticated service, not anonymous. Use Connect & authorize for OAuth, or configure an Authorization header in Edit."]),
    _npm("sentry", "Sentry", "Investigate Sentry errors, issues, and performance data.", "@sentry/mcp-server", "Sentry", "https://github.com/getsentry/sentry-mcp", ["SENTRY_ACCESS_TOKEN"], compatibility=["Requires Node.js >=22.13 and npx. AI-powered search tools additionally require a separately configured LLM provider; do not assume those tools are available or free."]),
    _npm("stripe", "Stripe", "Inspect customers, payments, subscriptions, and invoices.", "@stripe/mcp", "Stripe", "https://github.com/stripe/agent-toolkit", ["STRIPE_SECRET_KEY"]),
    _npm("supabase", "Supabase", "Manage Supabase projects, databases, and edge functions.", "@supabase/mcp-server-supabase", "Supabase", "https://github.com/supabase-community/supabase-mcp", ["SUPABASE_ACCESS_TOKEN"]),
    _npm("vercel", "Vercel", "Inspect deployments, projects, logs, and environment variables.", "vercel-mcp", "Vercel", "https://github.com/vercel/mcp-adapter", ["VERCEL_TOKEN"]),
    _uvx("aws", "AWS Documentation", "Read and search public AWS documentation, not private account resources.", "awslabs.aws-documentation-mcp-server@latest", "AWS Labs", "https://github.com/awslabs/mcp", compatibility=["Requires uv, Python, and network access to public documentation; AWS account credentials are not required"]),
    _npm("cloudflare", "Cloudflare", "Work with Cloudflare Workers, KV, R2, and DNS.", "@cloudflare/mcp-server-cloudflare", "Cloudflare", "https://github.com/cloudflare/mcp-server-cloudflare", ["CLOUDFLARE_API_TOKEN"]),
    _npm("mongodb", "MongoDB", "Query MongoDB collections and aggregations.", "@mongodb-js/mongodb-mcp-server", "MongoDB", "https://github.com/mongodb-js/mongodb-mcp-server", ["MDB_MCP_API_KEY", "MDB_MCP_API_CLIENT_ID", "MDB_MCP_API_CLIENT_SECRET"]),
    _npm("redis", "Redis", "Inspect and manage Redis data.", "@modelcontextprotocol/server-redis", "MCP community", "https://github.com/modelcontextprotocol/servers/tree/main/src/redis", ["REDIS_URL"]),
    _npm("duckdb", "DuckDB", "Run analytical SQL over local files.", "duckdb-mcp-server", "DuckDB community", "https://github.com/ktanaka101/duckdb_mcp_server", compatibility=["Requires DuckDB and local file access"]),
    _uvx("docker", "Docker", "Inspect and manage Docker containers and images.", "mcp-server-docker", "Docker community", "https://github.com/ckreiling/mcp-server-docker", compatibility=["Requires uv and Python >=3.12. This is ckreiling's Python package, not the unrelated npm namesake. Docker Engine access is highly privileged; never use a production host socket for testing."]),
    _npm("tavily", "Tavily", "Search and extract web research results.", "tavily-mcp", "Tavily", "https://github.com/tavily-ai/tavily-mcp", ["TAVILY_API_KEY"]),
    _npm("firecrawl", "Firecrawl", "Crawl and extract structured web content.", "firecrawl-mcp", "Firecrawl", "https://github.com/mendableai/firecrawl-mcp-server", ["FIRECRAWL_API_KEY"]),
    _npm("exa", "Exa", "Semantic web search for research workflows.", "exa-mcp-server", "Exa", "https://github.com/exa-labs/exa-mcp-server", ["EXA_API_KEY"]),
    _npm("perplexity", "Perplexity", "Cited web search and research.", "@perplexity-ai/mcp-server", "Perplexity", "https://github.com/perplexityai/modelcontextprotocol", ["PERPLEXITY_API_KEY"]),
)

# These catalog dispositions are not observed MCP failures. Keep original IDs discoverable.
_DEPRECATED = {
    "github", "gitlab", "postgres", "puppeteer", "brave-search", "slack",
    "google-drive", "everart", "mongodb", "redis", "sqlite", "notion",
}
_UNVERIFIED = {
    "duckdb": "Identity unresolved: configured npm package and advertised source return 404. The same-named PyPI distribution is not a verified replacement.",
    "vercel": "Identity mismatch: vercel-mcp on npm is zueai/vercel-api-mcp, while the advertised Vercel source is an HTTP framework adapter, not a deployment-management CLI.",
    "stripe": "Local CLI configuration needs review: current upstream documentation recommends remote OAuth and no longer documents this catalog's local command. No automatic transport migration.",
    "cloudflare": "Local CLI configuration needs review: current upstream documents multiple remote servers, not this catalog's local token-only command. Select and review a supported server explicitly.",
}


def _review_disposition(entry: CatalogEntry) -> CatalogEntry:
    if entry["id"] in _DEPRECATED:
        entry = {**entry, "status": "deprecated",
                 "status_reason": "Unavailable for catalog Add: package deprecated or upstream archived/unsupported; no maintained replacement has been validated."}
        if "modelcontextprotocol/servers/tree/" in entry["source_url"]:
            entry["source_url"] = entry["source_url"].replace("/servers/tree/", "/servers-archived/tree/")
        if entry["id"] == "mongodb":
            entry["status_reason"] = "Unavailable for catalog Add: npm marks this package renamed to mongodb-mcp-server. Replacement configuration and runtime need separate review."
    if entry["id"] in _UNVERIFIED:
        entry = {**entry, "status": "unverified", "status_reason": _UNVERIFIED[entry["id"]]}
        if entry["id"] in {"duckdb", "vercel"}:
            entry = {**entry, "command": "", "args": []}
    return entry


CATALOG = tuple(_review_disposition(entry) for entry in CATALOG)
CATALOG_BY_ID = {entry["id"]: entry for entry in CATALOG}
