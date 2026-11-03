"""Lesson 4 client: open GitHub login, then call the protected MCP tool."""

import asyncio
from pathlib import Path

import yaml
from fastmcp import Client


async def main() -> None:
    config = yaml.safe_load(Path(__file__).with_name("config.yaml").read_text())
    url = f"https://{config['ngrok_domain']}/mcp"
    async with Client(url, auth="oauth") as client:
        result = await client.call_tool("greet", {"name": "Caveman"})
        print(result.data)


if __name__ == "__main__":
    asyncio.run(main())
