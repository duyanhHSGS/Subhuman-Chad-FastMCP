"""Lesson 5: actual client-visible FastMCP metadata and live local calls."""

import asyncio
import json

import httpx2
import pytest
from fastmcp import Client
from mcp.types import TextResourceContents

import Lesson5


def test_discovery_includes_tools_resources_templates_prompts() -> None:
    async def verify() -> None:
        async with Client(Lesson5.mcp) as client:
            tools = [
                tool.model_dump(by_alias=True, exclude_none=True)
                for tool in await client.list_tools()
            ]
            resources = await client.list_resources()
            templates = await client.list_resource_templates()
            prompts = await client.list_prompts()

        assert {tool["name"] for tool in tools} == {
            "probe", "async_probe", "from_constructor"
        }
        probe = next(tool for tool in tools if tool["name"] == "probe")
        assert set(probe) == {
            "name", "title", "description", "icons",
            "inputSchema", "outputSchema", "annotations", "_meta"
        }
        assert probe["title"] == "The Fully Decorated Probe"
        assert {icon["theme"] for icon in probe["icons"]} == {"light", "dark"}
        assert probe["annotations"]["readOnlyHint"] is True
        assert probe["_meta"]["ui"]["visibility"] == ["model"]
        assert probe["_meta"]["fastmcp"]["version"] == "5"
        assert set(probe["inputSchema"]["required"]) == {"amount"}
        assert probe["inputSchema"]["additionalProperties"] is False
        assert probe["outputSchema"]["additionalProperties"] is False
        assert {str(resource.uri) for resource in resources} == {"lesson5://guide"}
        assert {str(template.uri_template) for template in templates} == {
            "lesson5://item/{item}"
        }
        assert {prompt.name for prompt in prompts} == {"hint"}

    asyncio.run(verify())


def test_real_calls_and_middleware(monkeypatch: pytest.MonkeyPatch) -> None:
    async def verify() -> None:
        monkeypatch.setattr(Lesson5.audit, "calls", 0)
        async with Client(Lesson5.mcp) as client:
            result = await client.call_tool("probe", {"amount": 4})
            assert result.structured_content == {
                "amount": 4, "scale": 2.0, "note": "demo", "total": 8.0
            }
            context_result = await client.call_tool("async_probe", {"word": "yep"})
            assert context_result.content
            assert context_result.content[0].type == "text"
            assert "async:yep:" in context_result.content[0].text
            constructor_result = await client.call_tool("from_constructor", {})
            assert constructor_result.content
            assert constructor_result.content[0].type == "text"
            assert constructor_result.content[0].text == "constructor-tool-ok"
            static = await client.read_resource("lesson5://guide")
            assert isinstance(static[0], TextResourceContents)
            assert static[0].text == "Lesson 5 resource reached."
            template = await client.read_resource("lesson5://item/mango")
            assert isinstance(template[0], TextResourceContents)
            assert template[0].text == "item=mango"
            prompt = await client.get_prompt("hint", {"topic": "MCP"})
            assert prompt.messages[0].content.type == "text"
            assert prompt.messages[0].content.text == "Inspect MCP components."
        assert Lesson5.audit.calls == 3

        app = Lesson5.mcp.http_app()
        async with app.lifespan(app):
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url="http://local"
            ) as client:
                response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"ok": True, "lesson": 5}

    asyncio.run(verify())


def test_strict_input_validation() -> None:
    async def verify() -> None:
        async with Client(Lesson5.mcp) as client:
            with pytest.raises(Exception):
                await client.call_tool("probe", {"amount": "4"})
            with pytest.raises(Exception):
                await client.call_tool("probe", {"amount": -1})

    asyncio.run(verify())


def test_inspect_is_actual_client_metadata(
    capsys: pytest.CaptureFixture[str],
) -> None:
    asyncio.run(Lesson5.inspect())
    packet = json.loads(capsys.readouterr().out)
    identity = packet["server_identity_from_python"]
    assert identity["name"] == "Lesson 5: FastMCP Kitchen Sink"
    assert identity["version"] == "5.0.0"
    assert len(identity["icons"]) == 2
    assert len(packet["tools"]) == 3
    assert len(packet["resources"]) == 1
    assert len(packet["templates"]) == 1
    assert len(packet["prompts"]) == 1
