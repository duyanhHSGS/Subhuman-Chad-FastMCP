"""Lesson 6 tests persistence, portability, and owner-only GitHub access offline."""

import asyncio
import shutil
from pathlib import Path
from types import SimpleNamespace

import httpx2
import pytest
import yaml
from fastmcp import settings
from fastmcp.server.auth.oauth_proxy import OAuthProxy
from mcp.shared.auth import OAuthClientInformationFull

import Lesson6


FAKE_CONFIG: dict[str, str | int] = {
    "port": 8766,
    "ngrok_authtoken": "FAKE_NGROK",
    "ngrok_domain": "example.ngrok.app",
    "github_client_id": "FAKE_CLIENT_ID",
    "github_client_secret": "FAKE_CLIENT_SECRET",
    "github_allowed_user_id": 42,
}


def test_frozen_executable_uses_external_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Lesson6.sys, "frozen", True, raising=False)
    monkeypatch.setattr(Lesson6.sys, "executable", str(tmp_path / "Elliot"))
    assert Lesson6.app_directory() == tmp_path


def test_client_registry_survives_restart_and_copy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Create OAuth registration, reopen it, and move it to a second folder."""
    monkeypatch.setattr(settings, "home", settings.home)
    pc1 = tmp_path / "pc1"
    pc1.mkdir()
    monkeypatch.setattr(Lesson6, "CONFIG", pc1 / "config.yaml")

    async def check() -> None:
        first = Lesson6.make_server(FAKE_CONFIG)
        assert isinstance(first.auth, OAuthProxy)
        client = OAuthClientInformationFull(
            client_id="ELLIOT_TEST_CLIENT", client_name="Elliot", client_secret="FAKE_CLIENT_SECRET"
        )
        await first.auth.register_client(client)

        restarted = Lesson6.make_server(FAKE_CONFIG)
        assert isinstance(restarted.auth, OAuthProxy)
        remembered = await restarted.auth.get_client("ELLIOT_TEST_CLIENT")
        assert remembered is not None and remembered.client_id == client.client_id

        pc2 = tmp_path / "pc2"
        pc2.mkdir()
        shutil.copytree(pc1 / "oauth-state", pc2 / "oauth-state")
        monkeypatch.setattr(Lesson6, "CONFIG", pc2 / "config.yaml")
        moved = Lesson6.make_server(FAKE_CONFIG)
        assert isinstance(moved.auth, OAuthProxy)
        remembered_again = await moved.auth.get_client("ELLIOT_TEST_CLIENT")
        assert remembered_again is not None and remembered_again.client_id == client.client_id

    asyncio.run(check())


def test_owner_only_with_fake_github_api() -> None:
    async def check() -> None:
        def github(request: httpx2.Request) -> httpx2.Response:
            auth = request.headers.get("Authorization")
            if auth == "Bearer OWNER":
                user_id = 42
            elif auth == "Bearer STRANGER":
                user_id = 7
            else:
                return httpx2.Response(401)
            if request.url.path == "/user":
                return httpx2.Response(200, json={"id": user_id, "login": "test"})
            return httpx2.Response(200, headers={"X-OAuth-Scopes": "user"})

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(github)) as client:
            verifier = Lesson6.OwnerOnly(42)
            verifier._http_client = client
            owner = await verifier.verify_token("OWNER")
            stranger = await verifier.verify_token("STRANGER")
            invalid = await verifier.verify_token("INVALID")
        assert owner is not None and owner.subject == "42"
        assert stranger is None
        assert invalid is None

    asyncio.run(check())


def test_http_requires_oauth(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "home", settings.home)
    monkeypatch.setattr(Lesson6, "CONFIG", tmp_path / "config.yaml")

    async def check() -> None:
        app = Lesson6.make_server(FAKE_CONFIG).http_app()
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
                wrong = await client.post(
                    "/mcp", json=request,
                    headers={**headers, "Authorization": "Bearer FAKE_TOKEN"},
                )
                discovery = await client.get("/.well-known/oauth-authorization-server")
        assert missing.status_code == 401
        assert wrong.status_code == 401
        assert discovery.status_code == 200

    asyncio.run(check())


def test_denies_unconfigured_owner() -> None:
    with pytest.raises(ValueError, match="github_allowed_user_id"):
        Lesson6.make_server({**FAKE_CONFIG, "github_allowed_user_id": 0})


def test_main_uses_shared_config_and_fake_tunnel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(FAKE_CONFIG), encoding="utf-8")
    monkeypatch.setattr(Lesson6, "CONFIG", config)
    events: list[str] = []

    def forward(port: int, **kwargs: str) -> SimpleNamespace:
        assert port == 8766
        assert kwargs == {"authtoken": "FAKE_NGROK", "domain": "example.ngrok.app"}
        events.append("forward")
        return SimpleNamespace(url=lambda: "https://example.ngrok.app")

    class FakeServer:
        def run(self, **kwargs: object) -> None:
            assert kwargs == {"transport": "http", "host": "127.0.0.1", "port": 8766}
            events.append("serve")

    def make_server(config_data: dict[str, str | int]) -> FakeServer:
        assert config_data == FAKE_CONFIG
        return FakeServer()

    monkeypatch.setattr(Lesson6, "make_server", make_server)
    monkeypatch.setattr(Lesson6.ngrok, "forward", forward)
    monkeypatch.setattr(Lesson6.ngrok, "disconnect", lambda url: events.append("disconnect"))
    Lesson6.main()
    assert events == ["forward", "serve", "disconnect"]
