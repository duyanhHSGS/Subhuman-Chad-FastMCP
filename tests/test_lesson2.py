"""Lesson 2 tests: mock the forwarder, never open a public tunnel."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastmcp import Client

from security import Lesson2


def test_greeting_tool() -> None:
    async def call_tool() -> None:
        async with Client(Lesson2.mcp) as client:
            result = await client.call_tool("greet", {"name": "Caveman"})
            assert result.data == "Hello, Caveman!"

    asyncio.run(call_tool())


def test_forwarding(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "port": 8766,
                "ngrok_authtoken": "FAKE_TOKEN",
                "ngrok_domain": "example.ngrok.app",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(Lesson2, "CONFIG", config)
    events: list[str] = []

    def forward(port: int, **options: str) -> SimpleNamespace:
        assert port == 8766
        assert options == {"authtoken": "FAKE_TOKEN", "domain": "example.ngrok.app"}
        events.append("forward")
        return SimpleNamespace(url=lambda: "https://example.ngrok.app")

    monkeypatch.setattr(Lesson2.ngrok, "forward", forward)
    monkeypatch.setattr(Lesson2.ngrok, "disconnect", lambda url: events.append("disconnect"))
    monkeypatch.setattr(Lesson2.mcp, "run", lambda **kwargs: events.append("serve"))
    Lesson2.main()
    assert events == ["forward", "serve", "disconnect"]


def test_example_has_no_credentials() -> None:
    example = yaml.safe_load((Path(Lesson2.__file__).resolve().parent.parent / "config_example.yaml").read_text())
    assert example["port"] == 8766
    assert not example["ngrok_authtoken"]
    assert not example["ngrok_domain"]
    assert not example["bearer_token"]
