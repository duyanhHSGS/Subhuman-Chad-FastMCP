"""Lesson 5: GitHub OAuth, but only one GitHub account gets in."""

from pathlib import Path

import ngrok
import yaml
from fastmcp import FastMCP
from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.oauth_proxy import OAuthProxy
from fastmcp.server.auth.providers.github import GitHubTokenVerifier
from key_value.aio.stores.memory import MemoryStore

CONFIG = Path(__file__).with_name("config.yaml")


class OwnerOnly(GitHubTokenVerifier):
    def __init__(self, github_user_id: int) -> None:
        super().__init__(required_scopes=["user"])
        self.github_user_id = str(github_user_id)

    async def verify_token(self, token: str) -> AccessToken | None:
        user = await super().verify_token(token)
        return user if user is not None and user.subject == self.github_user_id else None


def make_server(config: dict[str, str | int]) -> FastMCP:
    owner_id = int(config["github_allowed_user_id"])
    if owner_id <= 0:
        raise ValueError("Set github_allowed_user_id in config.yaml to your numeric GitHub ID")

    auth = OAuthProxy(
        upstream_authorization_endpoint="https://github.com/login/oauth/authorize",
        upstream_token_endpoint="https://github.com/login/oauth/access_token",
        upstream_client_id=str(config["github_client_id"]),
        upstream_client_secret=str(config["github_client_secret"]),
        token_verifier=OwnerOnly(owner_id),
        base_url=f"https://{config['ngrok_domain']}",
        client_storage=MemoryStore(),
    )
    mcp = FastMCP("Lesson 5 - GitHub Owner Only", auth=auth)

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
        print(f"Owner-only OAuth MCP: {tunnel.url()}/mcp", flush=True)
        mcp.run(transport="http", host="127.0.0.1", port=port)
    finally:
        ngrok.disconnect(tunnel.url())


if __name__ == "__main__":
    main()
