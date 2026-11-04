"""Lesson 7: GitHub login via Auth0, with no local OAuth sessions."""

import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import ngrok
import yaml
from fastmcp import FastMCP
from fastmcp.server.auth import RemoteAuthProvider
from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.providers.jwt import JWTVerifier
from pydantic import AnyHttpUrl


def app_directory() -> Path:
    return Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent


CONFIG = app_directory() / "config.yaml"


class GitHubOwnerJWT(JWTVerifier):
    def __init__(self, issuer: str, audience: str, github_user_id: int) -> None:
        super().__init__(
            jwks_uri=f"{issuer}.well-known/jwks.json", issuer=issuer,
            audience=audience, algorithm="RS256",
        )
        self.allowed_subject = f"github|{github_user_id}"

    async def verify_token(self, token: str) -> AccessToken | None:
        user = await super().verify_token(token)
        if (
            user is None or user.subject != self.allowed_subject
            or user.expires_at is None or user.expires_at <= time.time()
        ):
            return None
        nbf = user.claims.get("nbf")
        if nbf is not None and (type(nbf) not in (int, float) or nbf > time.time()):
            return None
        return user


def make_server(config: dict[str, str | int]) -> FastMCP:
    owner_id = int(config["github_allowed_user_id"])
    if owner_id <= 0:
        raise ValueError("Configure github_allowed_user_id with your numeric GitHub ID")

    issuer = str(config["auth0_issuer"]).strip().rstrip("/") + "/"
    url = urlsplit(issuer)
    if (
        url.scheme != "https" or not url.hostname
        or url.username is not None or url.password is not None
        or url.path != "/" or url.query or url.fragment
    ):
        raise ValueError("Configure auth0_issuer as your Auth0 HTTPS tenant URL")

    base_url = f"https://{config['ngrok_domain']}"
    auth = RemoteAuthProvider(
        token_verifier=GitHubOwnerJWT(issuer, f"{base_url}/mcp", owner_id),
        authorization_servers=[AnyHttpUrl(issuer)], base_url=base_url,
    )
    mcp = FastMCP("Lesson 7 - Stateless GitHub OAuth", auth=auth)

    @mcp.tool
    def greet(name: str) -> str:
        return f"Hello, {name}!"

    return mcp


def main() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    mcp = make_server(config)
    port = config["port"]
    tunnel = ngrok.forward(port, authtoken=config["ngrok_authtoken"], domain=config["ngrok_domain"])
    try:
        print(f"Stateless GitHub OAuth MCP: {tunnel.url()}/mcp", flush=True)
        mcp.run(transport="http", host="127.0.0.1", port=port)
    finally:
        ngrok.disconnect(tunnel.url())


if __name__ == "__main__":
    main()
