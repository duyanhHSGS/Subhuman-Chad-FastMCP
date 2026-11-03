"""Ask the Lesson 1 MCP server to call its greet tool (no network needed)."""

import asyncio

from fastmcp import Client

from Lesson1 import mcp


async def main() -> None:
    async with Client(mcp) as client:
        answer = await client.call_tool("greet", {"name": "dawg"})
        print(answer.data)


if __name__ == "__main__":
    asyncio.run(main())
