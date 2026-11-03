"""Verify the beginner MCP tool works through the real MCP protocol."""

import asyncio

from fastmcp import Client

from Lesson1 import greet, mcp


def test_greeting() -> None:
    assert greet("dawg") == "Hello, dawg!"


def test_mcp_tool() -> None:
    async def run_client() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool("greet", {"name": "dawg"})
            assert result.data == "Hello, dawg!"

    asyncio.run(run_client())
