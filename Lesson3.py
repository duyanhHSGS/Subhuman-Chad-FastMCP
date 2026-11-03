"""Lesson 3: protect a forwarded FastMCP server with a bearer token."""

from pathlib import Path

import ngrok
import yaml
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

CONFIG = Path(__file__).with_name("config.yaml")


def make_server(token: str) -> FastMCP:
    mcp = FastMCP(
        "Lesson 3 - Bearer Token",
        auth=StaticTokenVerifier({token: {"client_id": "lesson3", "scopes": []}}),
    )

    @mcp.tool
    def greet(name: str) -> str:
        return f"Hello, {name}!"

    return mcp


def main() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    port = config["port"]
    mcp = make_server(config["bearer_token"])
    tunnel = ngrok.forward(
        port, authtoken=config["ngrok_authtoken"], domain=config["ngrok_domain"]
    )
    try:
        print(f"Public MCP: {tunnel.url()}/mcp", flush=True)
        mcp.run(transport="http", host="127.0.0.1", port=port)
    finally:
        ngrok.disconnect(tunnel.url())


if __name__ == "__main__":
    main()
