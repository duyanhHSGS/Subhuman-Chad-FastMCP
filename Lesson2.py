"""Lesson 2: a simple FastMCP server forwarded through ngrok."""

from pathlib import Path

import ngrok
import yaml
from fastmcp import FastMCP

mcp = FastMCP("Subhuman-Chad Learning Lab")
CONFIG = Path(__file__).with_name("config.yaml")


@mcp.tool
def greet(name: str) -> str:
    return f"Hello, {name}!"


def main() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    port = config["port"]
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
