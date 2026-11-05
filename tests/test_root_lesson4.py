"""Lesson 4: verify every named core Tool field and real MCP behavior."""

import asyncio
import json

import pytest
from fastmcp import Client

import Lesson4

CORE_FIELDS = {
    "name", "title", "description", "icons",
    "inputSchema", "outputSchema", "annotations", "_meta",
}


def test_complete_tool_descriptor() -> None:
    async def verify() -> None:
        async with Client(Lesson4.mcp) as client:
            tools = await client.list_tools()
        assert len(tools) == 1
        descriptor = tools[0].model_dump(by_alias=True, exclude_none=True)
        assert set(descriptor) == CORE_FIELDS
        assert descriptor["name"] == "magic"
        assert descriptor["title"] == "Magic Counter - Full MCP Field Demo"
        assert "Examples" in descriptor["description"]
        assert len(descriptor["icons"]) == 2
        for icon in descriptor["icons"]:
            assert icon["src"].startswith("data:image/svg+xml;base64,")
            assert icon["mimeType"] == "image/svg+xml"
            assert icon["sizes"] == ["48x48"]
        assert {icon["theme"] for icon in descriptor["icons"]} == {"light", "dark"}
        assert descriptor["annotations"] == {
            "title": "Update counter",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": False,
        }
        assert descriptor["_meta"]["com.example.fastmcp/lessonNumber"] == 4
        inputs = descriptor["inputSchema"]
        assert set(inputs["required"]) == {"add", "multiply", "subtract"}
        assert inputs["properties"]["add"]["minimum"] == 0
        assert inputs["properties"]["add"]["maximum"] == 4_294_967_295
        assert inputs["properties"]["multiply"]["type"] == "number"
        output = descriptor["outputSchema"]
        assert output["additionalProperties"] is False
        assert set(output["required"]) == {
            "before", "add", "multiply", "subtract", "after"
        }

    asyncio.run(verify())


def test_real_client_calls_and_structured_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def verify() -> None:
        monkeypatch.setattr(Lesson4, "count", 0)
        async with Client(Lesson4.mcp) as client:
            first = await client.call_tool(
                "magic", {"add": 10, "multiply": 2.0, "subtract": 3}
            )
            assert first.is_error is False
            assert first.structured_content == {
                "before": 0.0, "add": 10, "multiply": 2.0,
                "subtract": 3, "after": 17.0,
            }
            second = await client.call_tool(
                "magic", {"add": 4, "multiply": 1.5, "subtract": 1}
            )
            assert second.structured_content is not None
            assert second.structured_content["after"] == 30.5
        assert Lesson4.count == 30.5

    asyncio.run(verify())


def test_invalid_inputs_and_overflow_never_mutate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def verify() -> None:
        monkeypatch.setattr(Lesson4, "count", 0)
        async with Client(Lesson4.mcp) as client:
            for invalid in (
                {"add": -1, "multiply": 1.0, "subtract": 0},
                {"add": 1, "multiply": 1.0, "subtract": 4_294_967_296},
                {"add": True, "multiply": 1.0, "subtract": 0},
            ):
                with pytest.raises(Exception):
                    await client.call_tool("magic", invalid)
                assert Lesson4.count == 0
            monkeypatch.setattr(Lesson4, "count", 1e308)
            with pytest.raises(Exception):
                await client.call_tool(
                    "magic", {"add": 0, "multiply": 2.0, "subtract": 0}
                )
            assert Lesson4.count == 1e308

    asyncio.run(verify())


def test_inspect_prints_real_client_descriptor(
    capsys: pytest.CaptureFixture[str],
) -> None:
    asyncio.run(Lesson4.inspect())
    descriptor = json.loads(capsys.readouterr().out)
    assert set(descriptor) == CORE_FIELDS
