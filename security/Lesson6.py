"""Lesson 6: portable, persistent, owner-only GitHub OAuth MCP."""

import json
import sys
from pathlib import Path

import ngrok
import yaml
from fastmcp import FastMCP, settings
from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.oauth_proxy import OAuthProxy
from fastmcp.server.auth.providers.github import GitHubTokenVerifier


def app_directory() -> Path:
    """Use the executable's folder when frozen, otherwise the script's folder."""
    return (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent.parent
    )


CONFIG = app_directory() / "config.yaml"


def rebase_moved_state(home: Path) -> None:
    """Correct file-store metadata paths after copying the portable folder."""
    for info_file in (home / "oauth-proxy").glob("*/*-info.json"):
        actual_dir = info_file.parent / info_file.name.removesuffix("-info.json")
        if not actual_dir.is_dir():
            raise FileNotFoundError(actual_dir)
        metadata = json.loads(info_file.read_text(encoding="utf-8"))
        current_dir = str(actual_dir.resolve())
        if metadata["directory"] != current_dir:
            metadata["directory"] = current_dir
            info_file.write_text(json.dumps(metadata), encoding="utf-8")


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
        raise ValueError("Set github_allowed_user_id in config.yaml")

    # FastMCP's default OAuth storage is encrypted and disk-backed.
    settings.home = CONFIG.parent / "oauth-state"
    rebase_moved_state(settings.home)
    auth = OAuthProxy(
        upstream_authorization_endpoint="https://github.com/login/oauth/authorize",
        upstream_token_endpoint="https://github.com/login/oauth/access_token",
        upstream_client_id=str(config["github_client_id"]),
        upstream_client_secret=str(config["github_client_secret"]),
        token_verifier=OwnerOnly(owner_id),
        base_url=f"https://{config['ngrok_domain']}",
    )
    mcp = FastMCP("Lesson 6 - Portable OAuth", auth=auth)

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
        print(f"Portable OAuth MCP: {tunnel.url()}/mcp", flush=True)
        mcp.run(transport="http", host="127.0.0.1", port=port)
    finally:
        ngrok.disconnect(tunnel.url())


if __name__ == "__main__":
    main()
