"""A tiny MCP server over stdio for tests: `uv run python tests/mcp_stub_server.py`."""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("stub")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@mcp.tool()
def echo(text: str) -> str:
    """Echo the text back."""
    return f"echo: {text}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
