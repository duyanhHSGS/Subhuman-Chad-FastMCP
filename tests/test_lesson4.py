"""Lesson 4 OAuth tests use fake GitHub settings and fake ngrok forwarding."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx2
import pytest
import yaml
from fastmcp.server.auth.providers.github import GitHubProvider

import Lesson4


SETTINGS: dict[str, str | int] = {
    "port": 8766,
    "ngrok_authtoken": "TEST_NGROK",
    "ngrok_domain": "example.ngrok.app",
    "github_client_id": "TEST_CLIENT_ID",
    "github_client_secret": "TEST_CLIENT_SECRET",
}


def test_github_login_required() -> None:
    async def check() -> None:
        mcp = Lesson4.make_server(SETTINGS)
        assert isinstance(mcp.auth, GitHubProvider)
        app = mcp.http_app()
        transport = httpx2.ASGITransport(app=app)
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
        headers = {"Accept": "application/json, text/event-stream"}
        async with app.lifespan(app):
            async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
                missing = await client.post("/mcp", json=request, headers=headers)
                fake_token = await client.post(
                    "/mcp",
                    json=request,
                    headers={**headers, "Authorization": "Bearer NOT_AN_OAUTH_TOKEN"},
                )
                discovery = await client.get("/.well-known/oauth-authorization-server")
        assert missing.status_code == 401
        assert fake_token.status_code == 401
        assert discovery.status_code == 200

    asyncio.run(check())


def test_ngrok_uses_shared_yaml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(SETTINGS), encoding="utf-8")
    monkeypatch.setattr(Lesson4, "CONFIG", config)
    events: list[str] = []

    def forward(port: int, **options: str) -> SimpleNamespace:
        assert port == 8766
        assert options == {"authtoken": "TEST_NGROK", "domain": "example.ngrok.app"}
        events.append("forward")
        return SimpleNamespace(url=lambda: "https://example.ngrok.app")

    monkeypatch.setattr(Lesson4.ngrok, "forward", forward)
    monkeypatch.setattr(Lesson4.ngrok, "disconnect", lambda url: events.append("disconnect"))
    monkeypatch.setattr(Lesson4.FastMCP, "run", lambda self, **kwargs: events.append("serve"))
    Lesson4.main()
    assert events == ["forward", "serve", "disconnect"]


def test_shared_example_has_empty_github_credentials() -> None:
    example = yaml.safe_load(Path(Lesson4.__file__).with_name("config_example.yaml").read_text())
    assert example["github_client_id"] == ""
    assert example["github_client_secret"] == ""
