"""Run the full Privacy Router MCP server over stdio."""

from server.mcp import mcp

if __name__ == "__main__":
    mcp.run(transport="stdio")
