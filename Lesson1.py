"""Lesson 1: expose one harmless Python function as an MCP tool."""

from fastmcp import FastMCP

mcp = FastMCP("Subhuman-Chad Learning Lab")


@mcp.tool
def greet(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {name}!"


def main() -> None:
    """Start the lesson server on localhost."""
    mcp.run(transport="http", host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
