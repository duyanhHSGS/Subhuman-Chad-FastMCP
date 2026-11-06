"""Lesson 1: expose one harmless Python function as an MCP tool."""

from fastmcp import FastMCP

mcp = FastMCP("Subhuman-Chad Learning Lab")
count = 0


@mcp.tool
def increase() -> int:
    global count
    count += 1
    return count


def main() -> None:
    mcp.run(transport="http", host="127.0.0.1", port=6969)


if __name__ == "__main__":
    main()
