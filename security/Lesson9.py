"""OAuth for any client, backed by one bearer token from config.yaml.

Only short-lived approvals and authorization codes use RAM; client IDs remain
valid after restarts. Approve only redirect URLs you trust.
"""

import base64
import hmac
import html
import json
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

import ngrok
import yaml
from fastmcp import FastMCP
from fastmcp.server.auth.auth import AccessToken, OAuthProvider
from mcp.server.auth.provider import (
    AuthorizationCode, AuthorizationParams, RefreshToken, TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.settings import ClientRegistrationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"
SCOPES = ["mcp:access"]
TEN_YEARS = 315_360_000


def encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


class BearerOAuth(OAuthProvider):
    def __init__(self, token: str, origin: str) -> None:
        super().__init__(base_url=origin, required_scopes=SCOPES,
                         client_registration_options=ClientRegistrationOptions(enabled=False))
        self.token, self.origin = token, origin.rstrip("/")
        self.pending: dict[str, tuple[float, str, AuthorizationParams]] = {}
        self.codes: dict[str, AuthorizationCode] = {}

    def client_id(self, redirects: list[str], scope: str) -> str:
        payload = encode(json.dumps([redirects, scope], separators=(",", ":")).encode())
        signature = encode(hmac.digest(self.token.encode(), payload.encode(), "sha256"))
        return f"l9_{payload}.{signature}"

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        try:
            payload, signature = client_id.removeprefix("l9_").split(".", 1)
            expected = encode(hmac.digest(self.token.encode(), payload.encode(), "sha256"))
            if not client_id.startswith("l9_") or not hmac.compare_digest(signature, expected):
                return None
            redirects, scope = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            return OAuthClientInformationFull(
                client_id=client_id, redirect_uris=redirects, scope=scope,
                token_endpoint_auth_method="none", grant_types=["authorization_code"],
                response_types=["code"],
            )
        except (ValueError, TypeError, UnicodeDecodeError, ValidationError):
            return None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        raise NotImplementedError("Use the stateless /register endpoint")

    async def register(self, request: Request) -> Response:
        try:
            meta = OAuthClientMetadata.model_validate(await request.json())
            redirects = [str(uri) for uri in meta.redirect_uris or []]
            client = await self.get_client(self.client_id(
                redirects, meta.scope or "mcp:access openid email offline_access"
            ))
            if client is None:
                raise ValueError("Invalid client")
        except (ValueError, TypeError, ValidationError):
            return JSONResponse({"error": "invalid_client_metadata"}, status_code=400)
        return JSONResponse(client.model_dump(mode="json", exclude_none=True),
                            status_code=201, headers={"Cache-Control": "no-store"})

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        ticket = secrets.token_urlsafe(32)
        self.pending[ticket] = (time.time() + 300, client.client_id, params)
        return f"{self.origin}/approve?{urlencode({'ticket': ticket})}"

    async def approve(self, request: Request) -> Response:
        headers = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
        form = await request.form() if request.method == "POST" else None
        ticket = form.get("ticket") if form is not None else request.query_params.get("ticket")
        pending = self.pending.get(ticket) if isinstance(ticket, str) else None
        if not isinstance(ticket, str) or pending is None or pending[0] < time.time():
            return HTMLResponse("Approval expired", status_code=400, headers=headers)
        if request.method == "GET":
            return HTMLResponse(
                "<h2>Approve OAuth client</h2>"
                f"<p>Redirect: {html.escape(str(pending[2].redirect_uri))}</p>"
                "<form method='post'>"
                f"<input type='hidden' name='ticket' value='{ticket}'>"
                "<input type='password' name='token' placeholder='Your config.yaml bearer' required>"
                "<button>Approve</button></form>", headers=headers,
            )
        supplied = form.get("token") if form is not None else None
        if not isinstance(supplied, str) or not hmac.compare_digest(supplied.encode(), self.token.encode()):
            return HTMLResponse("Incorrect bearer", status_code=403, headers=headers)
        _, client_id, params = self.pending.pop(ticket)
        code = secrets.token_urlsafe(32)
        self.codes[code] = AuthorizationCode(
            code=code, client_id=client_id, scopes=params.scopes or [],
            expires_at=time.time() + 120, code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource, subject="owner",
        )
        return RedirectResponse(
            construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state),
            status_code=303, headers=headers,
        )

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        code = self.codes.get(authorization_code)
        return code if code and code.client_id == client.client_id and code.expires_at > time.time() else None

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        code = self.codes.pop(authorization_code.code, None)
        if code is None or code.client_id != client.client_id or code.expires_at <= time.time():
            raise TokenError("invalid_grant", "Code expired or already used")
        return OAuthToken(access_token=self.token, token_type="Bearer", expires_in=TEN_YEARS,
                          scope=" ".join(code.scopes))

    async def load_access_token(self, token: str) -> AccessToken | None:
        if not hmac.compare_digest(token.encode(), self.token.encode()):
            return None
        return AccessToken(token=token, client_id="owner", subject="owner", scopes=SCOPES,
                           resource=f"{self.origin}/mcp", expires_at=None)

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        return None

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        raise TokenError("unsupported_grant_type", "No refresh tokens")

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """Rotate config.yaml's bearer and restart to revoke the shared token."""

    async def metadata(self, request: Request) -> Response:
        return JSONResponse({
            "issuer": self.origin + "/",
            "authorization_endpoint": self.origin + "/authorize",
            "token_endpoint": self.origin + "/token",
            "registration_endpoint": self.origin + "/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "token_endpoint_auth_methods_supported": ["none"],
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": SCOPES,
        }, headers={"Cache-Control": "no-store"})

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        routes = [
            Route(route.path, self.metadata, methods=["GET"])
            if route.path == "/.well-known/oauth-authorization-server" else route
            for route in super().get_routes(mcp_path)
        ]
        return routes + [Route("/register", self.register, methods=["POST"]),
                         Route("/approve", self.approve, methods=["GET", "POST"])]


def make_server(config: dict[str, str | int]) -> FastMCP:
    mcp = FastMCP("Lesson 9 - Universal Bearer OAuth", auth=BearerOAuth(
        str(config["bearer_token"]), f"https://{config['ngrok_domain']}"
    ))

    @mcp.tool
    def greet(name: str) -> str:
        return f"Hello, {name}!"

    return mcp


def main() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    mcp = make_server(config)
    tunnel = ngrok.forward(int(config["port"]), authtoken=str(config["ngrok_authtoken"]),
                           domain=str(config["ngrok_domain"]))
    try:
        print(f"OAuth MCP: {tunnel.url()}/mcp", flush=True)
        mcp.run(transport="http", host="127.0.0.1", port=int(config["port"]), path="/mcp")
    finally:
        ngrok.disconnect(tunnel.url())


if __name__ == "__main__":
    main()
