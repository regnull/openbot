"""Curated, opt-in MCP server catalog.

Entries are metadata for opt-in servers (stdio or remote HTTP); installing an entry stores it disabled so
OpenBot never executes a newly discovered third-party server without an explicit user action.
The catalog is reviewed against the official MCP Registry and upstream project documentation.
"""
from __future__ import annotations

from typing import TypedDict


class CatalogEntry(TypedDict):
    id: str
    name: str
    description: str
    provider: str
    source_url: str
    transport: str                           # "stdio" | "http"
    command: str                             # empty string for remote entries
    args: list[str]                          # empty list for remote entries
    url: str                                 # empty string for stdio entries
    required_credentials: list[str]
    compatibility: list[str]


def _npm(id: str, name: str, description: str, package: str, provider: str, source_url: str,
         credentials: list[str] | None = None, args: list[str] | None = None,
         compatibility: list[str] | None = None) -> CatalogEntry:
    return {"id": id, "name": name, "description": description, "provider": provider,
            "source_url": source_url, "transport": "stdio", "command": "npx",
            "args": ["-y", package, *(args or [])], "url": "",
            "required_credentials": credentials or [],
            "compatibility": compatibility or ["Requires Node.js and npx"]}


def _uvx(id: str, name: str, description: str, package: str, provider: str, source_url: str,
         credentials: list[str] | None = None, args: list[str] | None = None,
         compatibility: list[str] | None = None) -> CatalogEntry:
    return {"id": id, "name": name, "description": description, "provider": provider,
            "source_url": source_url, "transport": "stdio", "command": "uvx",
            "args": [package, *(args or [])], "url": "",
            "required_credentials": credentials or [],
            "compatibility": compatibility or ["Requires uv and Python"]}


def _remote(id: str, name: str, description: str, url: str, provider: str, source_url: str,
            credentials: list[str] | None = None,
            compatibility: list[str] | None = None) -> CatalogEntry:
    return {"id": id, "name": name, "description": description, "provider": provider,
            "source_url": source_url, "transport": "http", "command": "",
            "args": [], "url": url,
            "required_credentials": credentials or [],
            "compatibility": compatibility or ["Remote server – no local runtime required"]}


CATALOG: tuple[CatalogEntry, ...] = (
    _npm("filesystem", "Filesystem", "Read, write, search, and manage files in explicitly allowed directories.", "@modelcontextprotocol/server-filesystem", "MCP steering group", "https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem", compatibility=["Pass one or more allowed directory paths after the package name"]),
    _npm("git", "Git", "Inspect and manipulate local Git repositories.", "@modelcontextprotocol/server-git", "MCP steering group", "https://github.com/modelcontextprotocol/servers/tree/main/src/git", compatibility=["Requires Git"]),
    _npm("memory", "Memory", "Persist entities and relations in a local knowledge graph.", "@modelcontextprotocol/server-memory", "MCP steering group", "https://github.com/modelcontextprotocol/servers/tree/main/src/memory"),
    _npm("sequential-thinking", "Sequential Thinking", "Break complex problems into explicit reasoning steps.", "@modelcontextprotocol/server-sequential-thinking", "MCP steering group", "https://github.com/modelcontextprotocol/servers/tree/main/src/sequentialthinking"),
    _npm("time", "Time", "Time and timezone conversion utilities.", "@modelcontextprotocol/server-time", "MCP steering group", "https://github.com/modelcontextprotocol/servers/tree/main/src/time"),
    _npm("fetch", "Fetch", "Fetch web pages and return readable content.", "@modelcontextprotocol/server-fetch", "MCP steering group", "https://github.com/modelcontextprotocol/servers/tree/main/src/fetch"),
    _npm("github", "GitHub", "Search repositories and manage issues, pull requests, and files.", "@modelcontextprotocol/server-github", "MCP steering group", "https://github.com/modelcontextprotocol/servers/tree/main/src/github", ["GITHUB_PERSONAL_ACCESS_TOKEN"]),
    _npm("gitlab", "GitLab", "Work with GitLab projects, issues, and merge requests.", "@modelcontextprotocol/server-gitlab", "MCP steering group", "https://github.com/modelcontextprotocol/servers/tree/main/src/gitlab", ["GITLAB_PERSONAL_ACCESS_TOKEN", "GITLAB_API_URL"]),
    _npm("postgres", "PostgreSQL", "Inspect schemas and run PostgreSQL queries.", "@modelcontextprotocol/server-postgres", "MCP steering group", "https://github.com/modelcontextprotocol/servers/tree/main/src/postgres", ["DATABASE_URL"], compatibility=["Use a read-only database role where possible"]),
    _npm("sqlite", "SQLite", "Query and update SQLite databases.", "@modelcontextprotocol/server-sqlite", "MCP steering group", "https://github.com/modelcontextprotocol/servers/tree/main/src/sqlite", compatibility=["Pass the database path after the package name"]),
    _npm("puppeteer", "Puppeteer", "Automate a Chromium browser and capture pages.", "@modelcontextprotocol/server-puppeteer", "MCP steering group", "https://github.com/modelcontextprotocol/servers/tree/main/src/puppeteer", compatibility=["Requires a compatible Chromium installation"]),
    _npm("brave-search", "Brave Search", "Search the web using the Brave Search API.", "@modelcontextprotocol/server-brave-search", "MCP steering group", "https://github.com/modelcontextprotocol/servers/tree/main/src/brave-search", ["BRAVE_API_KEY"]),
    _npm("slack", "Slack", "Search conversations and interact with Slack workspaces.", "@modelcontextprotocol/server-slack", "MCP steering group", "https://github.com/modelcontextprotocol/servers/tree/main/src/slack", ["SLACK_BOT_TOKEN", "SLACK_TEAM_ID"]),
    _npm("google-drive", "Google Drive", "Search and read files in Google Drive.", "@modelcontextprotocol/server-gdrive", "MCP steering group", "https://github.com/modelcontextprotocol/servers/tree/main/src/gdrive", ["GOOGLE_APPLICATION_CREDENTIALS"]),
    _npm("everart", "EverArt", "Generate images through EverArt models.", "@modelcontextprotocol/server-everart", "EverArt", "https://github.com/modelcontextprotocol/servers/tree/main/src/everart", ["EVERART_API_KEY"]),
    {"id": "serena", "name": "Serena", "description": "Semantic code navigation, editing, and project memories for software agents.", "provider": "Oraios", "source_url": "https://github.com/oraios/serena", "transport": "stdio", "command": "uvx", "args": ["--from", "serena-agent", "serena", "start-mcp-server", "--project-from-cwd"], "url": "", "required_credentials": [], "compatibility": ["Requires uv; the upstream package exposes the serena executable and uses the current working directory as the project"]},
    _npm("context7", "Context7", "Retrieve current, version-specific library documentation for coding tasks.", "@upstash/context7-mcp", "Upstash", "https://github.com/upstash/context7", ["CONTEXT7_API_KEY"], compatibility=["API key may be optional depending on the Context7 plan"]),
    _npm("delimit", "Delimit", "Keep decisions, tasks, and handoffs on the local machine across AI coding assistants; merge gate for AI-written code.", "delimit-cli", "Delimit", "https://github.com/delimit-ai/delimit-mcp-server", args=["mcp"], compatibility=["Requires Node.js, npx, and Python 3.9+; the first run creates a virtualenv under ~/.delimit and installs the server's Python dependencies"]),
    _npm("playwright", "Playwright", "Browser automation using Playwright.", "@playwright/mcp", "Microsoft", "https://github.com/microsoft/playwright-mcp", compatibility=["Requires browser binaries; run the package's browser install step"]),
    _npm("notion", "Notion", "Search and update Notion pages and databases.", "@notionhq/notion-mcp-server", "Notion", "https://github.com/makenotion/notion-mcp-server", ["NOTION_TOKEN"]),
    _remote("linear", "Linear", "Read and manage Linear issues, projects, and cycles.", "https://mcp.linear.app/mcp", "Linear", "https://github.com/linear/linear-mcp"),
    _npm("sentry", "Sentry", "Investigate Sentry errors, issues, and performance data.", "@sentry/mcp-server", "Sentry", "https://github.com/getsentry/sentry-mcp", ["SENTRY_AUTH_TOKEN", "SENTRY_ORG"]),
    _npm("stripe", "Stripe", "Inspect customers, payments, subscriptions, and invoices.", "@stripe/mcp", "Stripe", "https://github.com/stripe/agent-toolkit", ["STRIPE_SECRET_KEY"]),
    _npm("supabase", "Supabase", "Manage Supabase projects, databases, and edge functions.", "@supabase/mcp-server-supabase", "Supabase", "https://github.com/supabase-community/supabase-mcp", ["SUPABASE_ACCESS_TOKEN"]),
    _npm("vercel", "Vercel", "Inspect deployments, projects, logs, and environment variables.", "vercel-mcp", "Vercel", "https://github.com/vercel/mcp-adapter", ["VERCEL_TOKEN"]),
    _uvx("aws", "AWS", "Explore AWS resources and infrastructure context.", "awslabs.aws-documentation-mcp-server@latest", "AWS Labs", "https://github.com/awslabs/mcp", compatibility=["Requires uv and AWS credentials/configuration when accessing private AWS resources"]),
    _npm("cloudflare", "Cloudflare", "Work with Cloudflare Workers, KV, R2, and DNS.", "@cloudflare/mcp-server-cloudflare", "Cloudflare", "https://github.com/cloudflare/mcp-server-cloudflare", ["CLOUDFLARE_API_TOKEN"]),
    _npm("mongodb", "MongoDB", "Query MongoDB collections and aggregations.", "@mongodb-js/mongodb-mcp-server", "MongoDB", "https://github.com/mongodb-js/mongodb-mcp-server", ["MDB_MCP_API_KEY", "MDB_MCP_API_CLIENT_ID", "MDB_MCP_API_CLIENT_SECRET"]),
    _npm("redis", "Redis", "Inspect and manage Redis data.", "@modelcontextprotocol/server-redis", "MCP community", "https://github.com/modelcontextprotocol/servers/tree/main/src/redis", ["REDIS_URL"]),
    _npm("duckdb", "DuckDB", "Run analytical SQL over local files.", "duckdb-mcp-server", "DuckDB community", "https://github.com/ktanaka101/duckdb_mcp_server", compatibility=["Requires DuckDB and local file access"]),
    _npm("docker", "Docker", "Inspect and manage Docker containers and images.", "mcp-server-docker", "Docker community", "https://github.com/ckreiling/mcp-server-docker", compatibility=["Requires Docker Engine access; treat as highly privileged"]),
    _npm("tavily", "Tavily", "Search and extract web research results.", "tavily-mcp", "Tavily", "https://github.com/tavily-ai/tavily-mcp", ["TAVILY_API_KEY"]),
    _npm("firecrawl", "Firecrawl", "Crawl and extract structured web content.", "firecrawl-mcp", "Firecrawl", "https://github.com/mendableai/firecrawl-mcp-server", ["FIRECRAWL_API_KEY"]),
    _npm("exa", "Exa", "Semantic web search for research workflows.", "exa-mcp-server", "Exa", "https://github.com/exa-labs/exa-mcp-server", ["EXA_API_KEY"]),
    _npm("perplexity", "Perplexity", "Cited web search and research.", "perplexity-mcp", "Perplexity", "https://github.com/ppl-ai/modelcontextprotocol", ["PERPLEXITY_API_KEY"]),
)

CATALOG_BY_ID = {entry["id"]: entry for entry in CATALOG}
