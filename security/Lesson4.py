"""Lesson 4: use GitHub OAuth instead of a manually shared bearer token."""

from pathlib import Path

import ngrok
import yaml
from fastmcp import FastMCP
from fastmcp.server.auth.providers.github import GitHubProvider
from key_value.aio.stores.memory import MemoryStore

CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"


def make_server(config: dict[str, str | int]) -> FastMCP:
    auth = GitHubProvider(
        client_id=str(config["github_client_id"]),
        client_secret=str(config["github_client_secret"]),
        base_url=f"https://{config['ngrok_domain']}",
        client_storage=MemoryStore(),
    )
    mcp = FastMCP("Lesson 4 - GitHub OAuth", auth=auth)

    @mcp.tool
    def greet(name: str) -> str:
        return f"Hello, {name}!"

    return mcp


def main() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    mcp = make_server(config)
    port = config["port"]
    tunnel = ngrok.forward(
        port, authtoken=config["ngrok_authtoken"], domain=config["ngrok_domain"]
    )
    try:
        print(f"OAuth MCP: {tunnel.url()}/mcp", flush=True)
        mcp.run(transport="http", host="127.0.0.1", port=port)
    finally:
        ngrok.disconnect(tunnel.url())


if __name__ == "__main__":
    main()
