"""Lesson 5 tests fake GitHub API replies; never contact real GitHub or ngrok."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx2
import pytest
import yaml

from security import Lesson5


SETTINGS: dict[str, str | int] = {
    "port": 8766,
    "ngrok_authtoken": "FAKE_NGROK",
    "ngrok_domain": "example.ngrok.app",
    "github_client_id": "FAKE_CLIENT_ID",
    "github_client_secret": "FAKE_CLIENT_SECRET",
    "github_allowed_user_id": 42,
}


def test_only_owner_passes_verified_github_identity() -> None:
    async def check() -> None:
        def github(request: httpx2.Request) -> httpx2.Response:
            token = request.headers.get("Authorization")
            if token == "Bearer OWNER":
                user_id = 42
            elif token == "Bearer STRANGER":
                user_id = 7
            else:
                return httpx2.Response(401)
            if request.url.path == "/user":
                return httpx2.Response(200, json={"id": user_id, "login": "test-user"})
            return httpx2.Response(200, headers={"X-OAuth-Scopes": "user"})

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(github)) as client:
            verifier = Lesson5.OwnerOnly(42)
            verifier._http_client = client
            allowed = await verifier.verify_token("OWNER")
            stranger = await verifier.verify_token("STRANGER")
            invalid = await verifier.verify_token("INVALID")

        assert allowed is not None and allowed.subject == "42"
        assert stranger is None
        assert invalid is None

    asyncio.run(check())


def test_oauth_requires_login() -> None:
    async def check() -> None:
        app = Lesson5.make_server(SETTINGS).http_app()
        transport = httpx2.ASGITransport(app=app)
        request = {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
        headers = {"Accept": "application/json, text/event-stream"}
        async with app.lifespan(app):
            async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
                missing = await client.post("/mcp", json=request, headers=headers)
                fake = await client.post(
                    "/mcp", json=request,
                    headers={**headers, "Authorization": "Bearer FAKE_TOKEN"},
                )
                discovery = await client.get("/.well-known/oauth-authorization-server")
        assert missing.status_code == 401
        assert fake.status_code == 401
        assert discovery.status_code == 200

    asyncio.run(check())


def test_owner_id_must_be_configured() -> None:
    with pytest.raises(ValueError, match="github_allowed_user_id"):
        Lesson5.make_server({**SETTINGS, "github_allowed_user_id": 0})


def test_forwarding_uses_shared_yaml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(SETTINGS), encoding="utf-8")
    monkeypatch.setattr(Lesson5, "CONFIG", config)
    events: list[str] = []

    def forward(port: int, **options: str) -> SimpleNamespace:
        assert port == 8766
        assert options == {"authtoken": "FAKE_NGROK", "domain": "example.ngrok.app"}
        events.append("forward")
        return SimpleNamespace(url=lambda: "https://example.ngrok.app")

    monkeypatch.setattr(Lesson5.ngrok, "forward", forward)
    monkeypatch.setattr(Lesson5.ngrok, "disconnect", lambda url: events.append("disconnect"))
    monkeypatch.setattr(Lesson5.FastMCP, "run", lambda self, **kwargs: events.append("serve"))
    Lesson5.main()
    assert events == ["forward", "serve", "disconnect"]


def test_shared_example_owner_is_not_configured() -> None:
    template = Path(Lesson5.__file__).resolve().parent.parent / "config_example.yaml"
    data = yaml.safe_load(template.read_text(encoding="utf-8"))
    assert data["github_allowed_user_id"] == 0
    assert data["github_client_id"] == ""
    assert data["github_client_secret"] == ""
