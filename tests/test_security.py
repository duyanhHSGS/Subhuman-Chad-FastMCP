"""Offline security contract tests: no tunnel, login, or real credentials."""

import asyncio
import json
import time
from pathlib import Path
from collections.abc import Callable

import pytest
import yaml
from fastmcp import Client, FastMCP
from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.providers.github import GitHubTokenVerifier
from fastmcp.server.auth.providers.jwt import JWTVerifier

from security import Lesson1, Lesson2, Lesson3, Lesson4, Lesson5, Lesson6, Lesson7


@pytest.fixture
def fake_config() -> dict[str, str | int]:
    return {
        "port": 6969,
        "ngrok_authtoken": "",
        "ngrok_domain": "example.test",
        "bearer_token": "local-test-token",
        "github_client_id": "fake-client",
        "github_client_secret": "fake-secret",
        "github_allowed_user_id": 123,
        "auth0_issuer": "https://auth.example.test/",
    }


def test_lesson1_greet_is_an_mcp_tool() -> None:
    async def verify() -> None:
        async with Client(Lesson1.mcp) as client:
            result = await client.call_tool("greet", {"name": "Caveman"})
            assert result.structured_content == {"result": "Hello, Caveman!"}

    asyncio.run(verify())


def test_sample_config_is_secret_free_and_has_expected_keys(
    fake_config: dict[str, str | int],
) -> None:
    path = Path(__file__).resolve().parent.parent / "config_example.yaml"
    sample = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert set(sample) == set(fake_config)
    assert sample["port"] == 6969
    for name in (
        "ngrok_authtoken", "ngrok_domain", "bearer_token",
        "github_client_id", "github_client_secret", "auth0_issuer",
    ):
        assert sample[name] == ""
    assert sample["github_allowed_user_id"] == 0


def test_security_lesson2_exposes_greeting() -> None:
    async def verify() -> None:
        async with Client(Lesson2.mcp) as client:
            result = await client.call_tool("greet", {"name": "Manager"})
            assert result.structured_content == {"result": "Hello, Manager!"}

    asyncio.run(verify())


def test_security_lesson3_has_bearer_token_auth() -> None:
    server = Lesson3.make_server("local-test-token")
    assert server.auth is not None

    async def verify() -> None:
        assert await server.get_tool("greet") is not None

    asyncio.run(verify())


def test_security_lesson4_constructs_github_oauth_without_network(
    fake_config: dict[str, str | int],
) -> None:
    server = Lesson4.make_server(fake_config)
    assert server.auth is not None
    assert server.name == "Lesson 4 - GitHub OAuth"


@pytest.mark.parametrize("make_server", [Lesson5.make_server, Lesson6.make_server, Lesson7.make_server])
def test_owner_only_servers_reject_unconfigured_id(
    make_server: Callable[[dict[str, str | int]], FastMCP],
    fake_config: dict[str, str | int],
) -> None:
    fake_config["github_allowed_user_id"] = 0
    with pytest.raises(ValueError, match="github_allowed_user_id"):
        make_server(fake_config)


@pytest.mark.parametrize(
    "issuer",
    [
        "http://auth.example.test/",
        "https://auth.example.test/path/",
        "https://user:pass@auth.example.test/",
        "https://auth.example.test/?key=1",
        "https://auth.example.test/#frag",
    ],
)
def test_lesson7_rejects_unsafe_issuer_urls(
    fake_config: dict[str, str | int], issuer: str
) -> None:
    fake_config["auth0_issuer"] = issuer
    with pytest.raises(ValueError, match="auth0_issuer"):
        Lesson7.make_server(fake_config)


def test_lesson7_accepts_valid_configuration(
    fake_config: dict[str, str | int],
) -> None:
    server = Lesson7.make_server(fake_config)
    assert server.name == "Lesson 7 - Stateless GitHub OAuth"
    assert server.auth is not None


@pytest.mark.parametrize("verifier_factory", [Lesson5.OwnerOnly, Lesson6.OwnerOnly])
def test_owner_only_github_verifier(
    monkeypatch: pytest.MonkeyPatch,
    verifier_factory: Callable[[int], GitHubTokenVerifier],
) -> None:
    async def fake_verify(_self: object, _token: str) -> AccessToken:
        return AccessToken(token="dummy", client_id="local", scopes=[], subject="123")

    monkeypatch.setattr(GitHubTokenVerifier, "verify_token", fake_verify)
    verifier = verifier_factory(123)
    assert asyncio.run(verifier.verify_token("dummy")) is not None
    other = verifier_factory(456)
    assert asyncio.run(other.verify_token("dummy")) is None


def test_lesson6_app_directory_when_frozen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(Lesson6.sys, "frozen", True, raising=False)
    monkeypatch.setattr(Lesson6.sys, "executable", str(tmp_path / "program"))
    assert Lesson6.app_directory() == tmp_path


def test_lesson6_rebases_portable_oauth_metadata(tmp_path: Path) -> None:
    home = tmp_path / "oauth-state"
    record = home / "oauth-proxy" / "registrations"
    actual = record / "client-abc"
    actual.mkdir(parents=True)
    metadata = record / "client-abc-info.json"
    metadata.write_text(
        json.dumps({"directory": "/previous/device", "kind": "client"}),
        encoding="utf-8",
    )
    Lesson6.rebase_moved_state(home)
    updated = json.loads(metadata.read_text(encoding="utf-8"))
    assert updated == {"directory": str(actual.resolve()), "kind": "client"}
    Lesson6.rebase_moved_state(home)
    assert json.loads(metadata.read_text(encoding="utf-8")) == updated


def test_lesson6_rebase_missing_directory_is_an_error(tmp_path: Path) -> None:
    record = tmp_path / "oauth-state" / "oauth-proxy" / "registrations"
    record.mkdir(parents=True)
    (record / "missing-info.json").write_text(
        json.dumps({"directory": "/old"}), encoding="utf-8"
    )
    with pytest.raises(FileNotFoundError):
        Lesson6.rebase_moved_state(tmp_path / "oauth-state")


def test_lesson7_jwt_verifies_owner_and_expiration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_token = AccessToken(
        token="dummy", client_id="local", scopes=[],
        subject="github|123", expires_at=int(time.time()) + 1000,
    )

    async def fake_verify(_self: object, _token: str) -> AccessToken:
        return owner_token

    monkeypatch.setattr(JWTVerifier, "verify_token", fake_verify)
    verifier = Lesson7.GitHubOwnerJWT("https://auth.example.test/", "local", 123)
    assert asyncio.run(verifier.verify_token("dummy")) is owner_token
    owner_token.subject = "github|456"
    assert asyncio.run(verifier.verify_token("dummy")) is None
    owner_token.subject = "github|123"
    owner_token.expires_at = int(time.time()) - 1
    assert asyncio.run(verifier.verify_token("dummy")) is None
    owner_token.expires_at = int(time.time()) + 1000
    owner_token.claims["nbf"] = int(time.time()) + 1000
    assert asyncio.run(verifier.verify_token("dummy")) is None
