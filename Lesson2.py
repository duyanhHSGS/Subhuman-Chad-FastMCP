"""Lesson 2: observe real MCP messages from this independent server."""

import asyncio
import json

import httpx2
from fastmcp import FastMCP

mcp = FastMCP("Lesson 2: Inside an MCP Call")
count = 0


@mcp.tool
def increase() -> int:
    """Increase this lesson's counter."""
    global count
    count += 1
    return count


async def main() -> None:
    # Real MCP messages to this file's own server; no ports or ngrok.
    app = mcp.http_app()
    transport = httpx2.ASGITransport(app=app)
    headers = {"Accept": "application/json, text/event-stream"}

    async with app.lifespan(app):
        async with httpx2.AsyncClient(transport=transport, base_url="http://local") as client:

            async def send(message: dict[str, object]) -> None:
                print("\nCLIENT -> SERVER (POST /mcp):")
                print(json.dumps(message, indent=2))
                response = await client.post("/mcp", json=message, headers=headers)
                response.raise_for_status()
                if session := response.headers.get("mcp-session-id"):
                    headers["mcp-session-id"] = session
                print(f"SERVER -> CLIENT (HTTP {response.status_code}):")
                print(response.text.strip() or "(no response body)")

            # 1. The client and server agree on how to communicate.
            await send({
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "Lesson2", "version": "1.0"},
                },
            })
            await send({"jsonrpc": "2.0", "method": "notifications/initialized"})

            # 2. The client discovers the registered tools.
            await send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

            # 3. The client calls increase() twice, using its MCP tool name.
            for request_id in (3, 4):
                await send({
                    "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                    "params": {"name": "increase", "arguments": {}},
                })


if __name__ == "__main__":
    asyncio.run(main())
