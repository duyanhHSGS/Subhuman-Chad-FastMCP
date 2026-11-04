"""Lesson 7: fake Auth0 JWT keys and HTTP requests, no public tunnel or login."""

import asyncio
import base64
import time
from pathlib import Path
from types import SimpleNamespace

import httpx2
import jwt
import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastmcp.server.auth import RemoteAuthProvider

import Lesson7


ISSUER = "https://test.auth0.com/"
AUDIENCE = "https://example.ngrok.app/mcp"
SETTINGS: dict[str, str | int] = {
    "port": 8766,
    "ngrok_authtoken": "FAKE_NGROK",
    "ngrok_domain": "example.ngrok.app",
    "github_allowed_user_id": 42,
    "auth0_issuer": ISSUER,
}


def test_auth0_jwt_verifies_identity_and_rejects_other_tokens() -> None:
    async def check() -> None:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pub = key.public_key().public_numbers()

        def b64(number: int) -> str:
            data = number.to_bytes((number.bit_length() + 7) // 8, "big")
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        jwks = {"keys": [{"kty": "RSA", "kid": "test-key", "use": "sig", "alg": "RS256", "n": b64(pub.n), "e": b64(pub.e)}]}
        requests: list[str] = []

        def get_jwks(request: httpx2.Request) -> httpx2.Response:
            requests.append(str(request.url))
            return httpx2.Response(200, json=jwks)

        now = int(time.time())

        def sign(**changes: str | int | None) -> str:
            claims: dict[str, str | int] = {
                "iss": ISSUER, "aud": AUDIENCE,
                "sub": "github|42", "exp": now + 3600,
                "iat": now,
            }
            for key_name, value in changes.items():
                if value is None:
                    claims.pop(key_name, None)
                else:
                    claims[key_name] = value
            return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": "test-key"})

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(get_jwks)) as client:
            verifier = Lesson7.GitHubOwnerJWT(ISSUER, AUDIENCE, 42)
            verifier._http_client = client
            allowed = await verifier.verify_token(sign())
            stranger = await verifier.verify_token(sign(sub="github|7"))
            other_provider = await verifier.verify_token(sign(sub="google-oauth2|42"))
            bad_audience = await verifier.verify_token(sign(aud="https://other.example/mcp"))
            bad_issuer = await verifier.verify_token(sign(iss="https://other.auth0.com/"))
            expired = await verifier.verify_token(sign(exp=now - 10))
            no_exp = await verifier.verify_token(sign(exp=None))
            future = await verifier.verify_token(sign(nbf=now + 600))
            broken = await verifier.verify_token("not-a-jwt")
        assert allowed is not None and allowed.subject == "github|42"
        assert all(item is None for item in (
            stranger, other_provider, bad_audience, bad_issuer, expired, no_exp, future, broken
        ))
        assert requests and all(path == f"{ISSUER}.well-known/jwks.json" for path in requests)

    asyncio.run(check())


def test_remote_auth_has_no_client_registry_or_oauth_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Lesson7, "CONFIG", tmp_path / "config.yaml")
    server = Lesson7.make_server(SETTINGS)
    assert isinstance(server.auth, RemoteAuthProvider)
    verifier = server.auth.token_verifier
    assert isinstance(verifier, Lesson7.GitHubOwnerJWT)
    assert verifier.audience == AUDIENCE
    assert verifier.issuer == ISSUER
    assert not list(tmp_path.iterdir())


def test_protected_mcp_and_discovery() -> None:
    async def check() -> None:
        app = Lesson7.make_server(SETTINGS).http_app()
        transport = httpx2.ASGITransport(app=app)
        data = {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
        headers = {"Accept": "application/json, text/event-stream"}
        async with app.lifespan(app):
            async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
                anonymous = await client.post("/mcp", json=data, headers=headers)
                metadata = await client.get("/.well-known/oauth-protected-resource/mcp")
                fake_token = await client.post(
                    "/mcp", json=data, headers={**headers, "Authorization": "Bearer FAKE"}
                )
        assert anonymous.status_code == 401
        assert fake_token.status_code == 401
        assert metadata.status_code == 200
        assert metadata.json()["authorization_servers"] == [ISSUER]
        assert metadata.json()["resource"] == AUDIENCE

    asyncio.run(check())


def test_no_owner_or_auth0_issuer_rejected() -> None:
    with pytest.raises(ValueError, match="github_allowed_user_id"):
        Lesson7.make_server({**SETTINGS, "github_allowed_user_id": 0})
    for issuer in ("", "http://test.auth0.com/", "https://test.auth0.com/path", "https://test.auth0.com/?x=1"):
        with pytest.raises(ValueError, match="auth0_issuer"):
            Lesson7.make_server({**SETTINGS, "auth0_issuer": issuer})


def test_frozen_executable_uses_external_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Lesson7.sys, "frozen", True, raising=False)
    monkeypatch.setattr(Lesson7.sys, "executable", str(tmp_path / "Elliot"))
    assert Lesson7.app_directory() == tmp_path


def test_main_forwarding_is_fake(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(SETTINGS), encoding="utf-8")
    monkeypatch.setattr(Lesson7, "CONFIG", path)
    events: list[str] = []

    def forward(port: int, **kwargs: str) -> SimpleNamespace:
        assert port == 8766
        assert kwargs == {"authtoken": "FAKE_NGROK", "domain": "example.ngrok.app"}
        events.append("forward")
        return SimpleNamespace(url=lambda: "https://example.ngrok.app")

    monkeypatch.setattr(Lesson7.ngrok, "forward", forward)
    monkeypatch.setattr(Lesson7.ngrok, "disconnect", lambda url: events.append("disconnect"))
    monkeypatch.setattr(Lesson7.FastMCP, "run", lambda self, **kw: events.append("run"))
    Lesson7.main()
    assert events == ["forward", "run", "disconnect"]


def test_example_has_no_auth0_issuer() -> None:
    example = yaml.safe_load(Path(Lesson7.__file__).with_name("config_example.yaml").read_text())
    assert example["auth0_issuer"] == ""
    assert example["github_allowed_user_id"] == 0
