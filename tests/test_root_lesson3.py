"""Lesson 3 tests: exact schemas, real structured output, and uint validation."""

import asyncio

import pytest
from fastmcp import Client

import Lesson3


def test_tool_descriptor_is_structured() -> None:
    async def verify() -> None:
        tool = await Lesson3.mcp.get_tool("magic")
        assert tool is not None
        descriptor = tool.to_mcp_tool().model_dump(by_alias=True, exclude_none=True)
        assert descriptor["name"] == "magic"
        assert descriptor["title"] == "Magic Counter"
        inputs = descriptor["inputSchema"]
        assert set(inputs["required"]) == {"add", "multiply", "subtract"}
        assert inputs["properties"]["add"]["minimum"] == 0
        assert inputs["properties"]["subtract"]["minimum"] == 0
        assert inputs["properties"]["multiply"]["type"] == "number"
        assert inputs["properties"]["add"]["examples"] == [0, 1, 4, 10, 100, 4_294_967_295]
        assert inputs["properties"]["subtract"]["examples"] == [0, 1, 3, 10, 100, 4_294_967_295]
        assert inputs["properties"]["multiply"]["examples"] == [0.0, 0.5, 1.0, 1.5, 2.0, -1.0]
        assert "Worked examples, in order" in descriptor["description"]
        assert "Example structuredContent" in descriptor["description"]
        outputs = descriptor["outputSchema"]
        assert all(len(prop["examples"]) >= 3 for prop in outputs["properties"].values())
        assert set(outputs["required"]) == {
            "before", "add", "multiply", "subtract", "after"
        }
        assert outputs["properties"]["after"]["type"] == "number"
        assert descriptor["annotations"]["readOnlyHint"] is False
        assert descriptor["annotations"]["idempotentHint"] is False

    asyncio.run(verify())


def test_magic_mcp_calls_preserve_in_process_state(monkeypatch: pytest.MonkeyPatch) -> None:
    async def verify() -> None:
        monkeypatch.setattr(Lesson3, "count", 0)
        async with Client(Lesson3.mcp) as client:
            first = await client.call_tool("magic", {
                "add": 10, "multiply": 2.0, "subtract": 3
            })
            assert first.is_error is False
            assert first.structured_content == {
                "before": 0.0, "add": 10, "multiply": 2.0, "subtract": 3, "after": 17.0
            }
            second = await client.call_tool("magic", {
                "add": 4, "multiply": 1.5, "subtract": 1
            })
            assert second.structured_content == {
                "before": 17.0, "add": 4, "multiply": 1.5, "subtract": 1, "after": 30.5
            }
            assert Lesson3.count == 30.5

    asyncio.run(verify())


def test_invalid_uint_does_not_mutate_state(monkeypatch: pytest.MonkeyPatch) -> None:
    async def verify() -> None:
        monkeypatch.setattr(Lesson3, "count", 0)
        async with Client(Lesson3.mcp) as client:
            for invalid_args in (
                {"add": -1, "multiply": 2.0, "subtract": 0},
                {"add": 1, "multiply": 2.0, "subtract": -1},
                {"add": True, "multiply": 2.0, "subtract": 0},
            ):
                with pytest.raises(Exception):
                    await client.call_tool("magic", invalid_args, raise_on_error=True)
                assert Lesson3.count == 0

    asyncio.run(verify())
