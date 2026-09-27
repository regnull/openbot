# MCP catalog

OpenBot's Settings catalog is a curated, opt-in index of 35 MCP servers. Metadata is kept in `backend/openbot/mcp/catalog.py` and includes the provider, upstream source, install command, credentials, and compatibility notes. The initial review basis is the official Model Context Protocol servers repository plus each provider's upstream repository (links are shown in Settings). Catalog metadata is not a trust decision: entries are installed disabled, and users must review, enable, connect, and grant tools explicitly.

The catalog intentionally includes both local stdio packages and providers that may publish a different runner (for example uvx). Those compatibility notes are displayed before installation so users can correct the command for their platform rather than silently executing an unverified command.
