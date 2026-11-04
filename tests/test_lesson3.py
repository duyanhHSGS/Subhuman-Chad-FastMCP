"""Lesson 3 checks the bearer lock without contacting the public internet."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx2
import pytest
import yaml

from security import Lesson3


def test_bearer_authorization() -> None:
    async def check() -> None:
        app = Lesson3.make_server("CORRECT_TEST_TOKEN").http_app()
        transport = httpx2.ASGITransport(app=app)
        message = {
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
                missing = await client.post("/mcp", json=message, headers=headers)
                wrong = await client.post(
                    "/mcp", json=message,
                    headers={**headers, "Authorization": "Bearer WRONG_TEST_TOKEN"},
                )
                correct = await client.post(
                    "/mcp", json=message,
                    headers={**headers, "Authorization": "Bearer CORRECT_TEST_TOKEN"},
                )
        assert missing.status_code == 401
        assert wrong.status_code == 401
        assert correct.status_code == 200

    asyncio.run(check())


def test_forwarding(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({
        "port": 8767, "ngrok_authtoken": "TEST_NGROK",
        "ngrok_domain": "example.ngrok.app", "bearer_token": "TEST_BEARER",
    }), encoding="utf-8")
    monkeypatch.setattr(Lesson3, "CONFIG", config)
    events: list[str] = []

    def forward(port: int, **options: str) -> SimpleNamespace:
        assert port == 8767
        assert options == {"authtoken": "TEST_NGROK", "domain": "example.ngrok.app"}
        events.append("forward")
        return SimpleNamespace(url=lambda: "https://example.ngrok.app")

    class DummyServer:
        def run(self, **kwargs: object) -> None:
            assert kwargs == {"transport": "http", "host": "127.0.0.1", "port": 8767}
            events.append("serve")

    def make_server(token: str) -> DummyServer:
        assert token == "TEST_BEARER"
        return DummyServer()

    monkeypatch.setattr(Lesson3, "make_server", make_server)
    monkeypatch.setattr(Lesson3.ngrok, "forward", forward)
    monkeypatch.setattr(Lesson3.ngrok, "disconnect", lambda url: events.append("disconnect"))
    Lesson3.main()
    assert events == ["forward", "serve", "disconnect"]


def test_example_is_secret_free() -> None:
    file = Path(Lesson3.__file__).resolve().parent.parent / "config_example.yaml"
    data = yaml.safe_load(file.read_text(encoding="utf-8"))
    assert data == {
        "port": 8766, "ngrok_authtoken": "", "ngrok_domain": "", "bearer_token": "",
        "github_client_id": "", "github_client_secret": "",
        "github_allowed_user_id": 0,
        "auth0_issuer": "",
    }
