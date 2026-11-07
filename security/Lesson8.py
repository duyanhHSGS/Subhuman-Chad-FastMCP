"""Lesson 8: one configured bearer token, presented through an OAuth code flow.

Client registration is signed and stateless; authorization codes and approval
requests exist only in RAM. The sole long-lived credential is config.yaml's
bearer_token. Restarting the server does not invalidate that bearer or its
registered OAuth client IDs.
"""

import base64
import hashlib
import hmac
import html
import json
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

import ngrok
import yaml
from fastmcp import FastMCP
from fastmcp.server.auth.auth import AccessToken, OAuthProvider
from mcp.server.auth.settings import ClientRegistrationOptions
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"
CODE_LIFETIME_SECONDS = 120
APPROVAL_LIFETIME_SECONDS = 300
BEARER_ADVERTISED_LIFETIME_SECONDS = 315_360_000  # 10 years
SCOPES = ["mcp:access"]
# These are ChatGPT's documented callback URLs, not arbitrary third-party URLs.
STABLE_CALLBACK = "https://chatgpt.com/connector_platform_oauth_redirect"
SCOPED_CALLBACK = re.compile(r"https://chatgpt\.com/connector/oauth/[A-Za-z0-9_-]+\Z")


def _encoded(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decoded(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _safe_callback(url: str) -> bool:
    return url == STABLE_CALLBACK or SCOPED_CALLBACK.fullmatch(url) is not None


class SingleBearerOAuth(OAuthProvider):
    """Small OAuth facade: DCR + PKCE + owner approval, no persistent state."""

    def __init__(self, bearer: str, base_url: str) -> None:
        if len(bearer) < 32:
            raise ValueError(
                "Configure a high-entropy bearer_token (at least 32 characters)"
            )
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.path not in ("", "/")
        ):
            raise ValueError("OAuth base_url must be a public HTTPS origin")
        super().__init__(
            base_url=base_url,
            required_scopes=SCOPES,
            client_registration_options=ClientRegistrationOptions(enabled=False),
        )
        self._bearer = bearer
        self._resource = f"{base_url.rstrip('/')}/mcp"
        self._approval: dict[str, tuple[float, str, AuthorizationParams]] = {}
        self._codes: dict[str, AuthorizationCode] = {}

    def _sign(self, payload: str) -> str:
        signature = hmac.new(
            self._bearer.encode(), payload.encode(), hashlib.sha256
        ).digest()
        return _encoded(signature)

    def _client_id(self, redirects: list[str]) -> str:
        payload = _encoded(
            json.dumps(sorted(redirects), separators=(",", ":")).encode()
        )
        return f"scf_{payload}.{self._sign(payload)}"

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        if not client_id.startswith("scf_") or len(client_id) > 3072:
            return None
        try:
            payload, signature = client_id[4:].split(".", 1)
            if not hmac.compare_digest(signature, self._sign(payload)):
                return None
            redirects = json.loads(_decoded(payload))
            if (
                not isinstance(redirects, list)
                or not (1 <= len(redirects) <= 4)
                or any(
                    not isinstance(uri, str) or not _safe_callback(uri)
                    for uri in redirects
                )
                or self._client_id(redirects) != client_id
            ):
                return None
            return OAuthClientInformationFull(
                client_id=client_id,
                redirect_uris=redirects,
                grant_types=["authorization_code"],
                response_types=["code"],
                token_endpoint_auth_method="none",
                scope="mcp:access openid email offline_access",
            )
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """Registration is handled without saving client records in /register."""
        raise NotImplementedError("Use the stateless /register endpoint")

    async def _register(self, request: Request) -> Response:
        raw = await request.body()
        if len(raw) > 8192:
            return JSONResponse({"error": "invalid_client_metadata"}, status_code=400)
        try:
            data = json.loads(raw)
            metadata = OAuthClientMetadata.model_validate(data)
            redirects = [str(uri) for uri in metadata.redirect_uris or []]
            if (
                not redirects
                or len(redirects) > 4
                or not all(map(_safe_callback, redirects))
            ):
                raise ValueError("Only ChatGPT callback URIs are allowed")
            if (
                "authorization_code" not in metadata.grant_types
                or "code" not in metadata.response_types
            ):
                raise ValueError("Authorization code flow is required")
        except (ValueError, ValidationError, UnicodeDecodeError):
            return JSONResponse({"error": "invalid_client_metadata"}, status_code=400)
        client_id = self._client_id(redirects)
        client = await self.get_client(client_id)
        if client is None:
            return JSONResponse({"error": "invalid_client_metadata"}, status_code=400)
        return JSONResponse(
            client.model_dump(mode="json", exclude_none=True),
            status_code=201,
            headers={"Cache-Control": "no-store"},
        )

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        if (
            params.resource is not None
            and params.resource.rstrip("/") != self._resource
        ):
            raise AuthorizeError("invalid_target", "Unknown MCP resource")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", params.code_challenge):
            raise AuthorizeError("invalid_request", "S256 PKCE challenge required")
        ticket = secrets.token_urlsafe(32)
        self._approval[ticket] = (
            time.time() + APPROVAL_LIFETIME_SECONDS,
            client.client_id,
            params,
        )
        return f"{str(self.base_url).rstrip('/')}/approve?ticket={ticket}"

    def _get_ticket(self, ticket: str) -> tuple[str, AuthorizationParams] | None:
        pending = self._approval.get(ticket)
        if pending is None:
            return None
        expires_at, client_id, params = pending
        if expires_at <= time.time():
            self._approval.pop(ticket, None)
            return None
        return client_id, params

    async def _approve(self, request: Request) -> Response:
        headers = {
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self' https://chatgpt.com; base-uri 'none'",
            "X-Content-Type-Options": "nosniff",
        }
        if request.method == "GET":
            ticket = request.query_params.get("ticket", "")
            if self._get_ticket(ticket) is None:
                return HTMLResponse(
                    "Authorization request expired", status_code=400, headers=headers
                )
            page = (
                "<!doctype html><html><head><title>MCP owner authorization</title>"
                "<meta name='viewport' content='width=device-width, initial-scale=1'></head>"
                "<body><h2>Authorize ChatGPT for MCP</h2>"
                "<p>Enter your existing bearer token from config.yaml to approve.</p>"
                "<form method='post' action='/approve'>"
                f"<input type='hidden' name='ticket' value='{html.escape(ticket, quote=True)}'>"
                "<input type='password' name='bearer' autocomplete='off' required>"
                "<button type='submit'>Authorize</button></form></body></html>"
            )
            return HTMLResponse(page, headers=headers)

        form = await request.form()
        ticket_value, bearer_value = form.get("ticket"), form.get("bearer")
        if not isinstance(ticket_value, str) or not isinstance(bearer_value, str):
            return HTMLResponse("Invalid request", status_code=400, headers=headers)
        pending = self._get_ticket(ticket_value)
        if pending is None:
            return HTMLResponse(
                "Authorization request expired", status_code=400, headers=headers
            )
        if not hmac.compare_digest(bearer_value.encode(), self._bearer.encode()):
            return HTMLResponse(
                "Invalid bearer token", status_code=403, headers=headers
            )

        self._approval.pop(ticket_value, None)
        client_id, params = pending
        code = secrets.token_urlsafe(32)
        self._codes[code] = AuthorizationCode(
            code=code,
            client_id=client_id,
            scopes=params.scopes or [],
            expires_at=time.time() + CODE_LIFETIME_SECONDS,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=self._resource,
            subject="owner",
        )
        return RedirectResponse(
            construct_redirect_uri(
                str(params.redirect_uri), code=code, state=params.state
            ),
            status_code=303,
            headers=headers,
        )

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        code = self._codes.get(authorization_code)
        if (
            code is None
            or code.expires_at <= time.time()
            or code.client_id != client.client_id
        ):
            return None
        return code

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        code = self._codes.pop(authorization_code.code, None)
        if (
            code is None
            or code.client_id != client.client_id
            or code.expires_at <= time.time()
        ):
            raise TokenError(
                "invalid_grant", "Authorization code already used or expired"
            )
        return OAuthToken(
            access_token=self._bearer,
            token_type="Bearer",
            expires_in=BEARER_ADVERTISED_LIFETIME_SECONDS,
            scope=" ".join(code.scopes),
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        if not hmac.compare_digest(token.encode(), self._bearer.encode()):
            return None
        return AccessToken(
            token=token,
            client_id="single-owner",
            subject="owner",
            scopes=["mcp:access", "openid", "email", "offline_access"],
            resource=self._resource,
            expires_at=None,
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        return None

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        raise TokenError("unsupported_grant_type", "No refresh tokens are issued")

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """Rotate config.yaml's bearer_token to revoke the one shared credential."""

    async def _metadata(self, request: Request) -> Response:
        base = str(self.base_url).rstrip("/")
        return JSONResponse(
            {
                "issuer": base + "/",
                "authorization_endpoint": base + "/authorize",
                "token_endpoint": base + "/token",
                "registration_endpoint": base + "/register",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code"],
                "token_endpoint_auth_methods_supported": ["none"],
                "code_challenge_methods_supported": ["S256"],
                "scopes_supported": SCOPES,
            },
            headers={"Cache-Control": "no-store"},
        )

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        routes = super().get_routes(mcp_path)
        routes = [
            Route(
                "/.well-known/oauth-authorization-server",
                self._metadata,
                methods=["GET"],
            )
            if route.path == "/.well-known/oauth-authorization-server"
            else route
            for route in routes
        ]
        return routes + [
            Route("/register", self._register, methods=["POST"]),
            Route("/approve", self._approve, methods=["GET", "POST"]),
        ]


def make_server(config: dict[str, str | int]) -> FastMCP:
    base_url = f"https://{config['ngrok_domain']}"
    auth = SingleBearerOAuth(str(config["bearer_token"]), base_url)
    mcp = FastMCP("Lesson 8 - Single Bearer OAuth", auth=auth)

    @mcp.tool
    def greet(name: str) -> str:
        return f"Hello, {name}!"

    return mcp


def main() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    mcp = make_server(config)
    port = int(config["port"])
    tunnel = ngrok.forward(
        port,
        authtoken=str(config["ngrok_authtoken"]),
        domain=str(config["ngrok_domain"]),
    )
    try:
        print(f"Single-bearer OAuth MCP: {tunnel.url()}/mcp", flush=True)
        mcp.run(transport="http", host="127.0.0.1", port=port, path="/mcp")
    finally:
        ngrok.disconnect(tunnel.url())


if __name__ == "__main__":
    main()
