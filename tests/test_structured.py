"""Local integration tests for the six structured FastMCP lessons."""

import asyncio

import httpx2
import pytest
from fastmcp import Client, FastMCP
from mcp.types import TextResourceContents

from structured import Lesson1, Lesson2, Lesson3, Lesson4, Lesson5, Lesson6


def test_lesson1_increase_is_stateful(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Lesson1, "count", 0)

    async def verify() -> None:
        async with Client(Lesson1.mcp) as client:
            assert [tool.name for tool in await client.list_tools()] == ["increase"]
            first = await client.call_tool("increase", {})
            second = await client.call_tool("increase", {})
            assert first.structured_content == {"result": 1}
            assert second.structured_content == {"result": 2}

    asyncio.run(verify())
    assert Lesson1.count == 2


def test_lesson2_exchanges_json_rpc_without_a_listener(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(Lesson2, "count", 0)
    asyncio.run(Lesson2.main())
    transcript = capsys.readouterr().out
    assert '"method": "initialize"' in transcript
    assert '"method": "tools/list"' in transcript
    assert transcript.count('"method": "tools/call"') == 2
    assert "SERVER -> CLIENT (HTTP" in transcript
    assert Lesson2.count == 2


def test_lesson3_structured_arithmetic_and_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Lesson3, "count", 0.0)

    async def verify() -> None:
        async with Client(Lesson3.mcp) as client:
            first = await client.call_tool(
                "magic", {"add": 10, "multiply": 2.0, "subtract": 3}
            )
            second = await client.call_tool(
                "magic", {"add": 4, "multiply": 1.5, "subtract": 1}
            )
        assert first.structured_content == {
            "before": 0.0, "add": 10, "multiply": 2.0,
            "subtract": 3, "after": 17.0,
        }
        assert second.structured_content == {
            "before": 17.0, "add": 4, "multiply": 1.5,
            "subtract": 1, "after": 30.5,
        }

    asyncio.run(verify())
    assert Lesson3.count == 30.5


@pytest.mark.parametrize(
    "arguments",
    [
        {"add": -1, "multiply": 1.0, "subtract": 0},
        {"add": 4_294_967_296, "multiply": 1.0, "subtract": 0},
        {"add": 0, "multiply": float("inf"), "subtract": 0},
        {"add": 0, "multiply": 1.0, "subtract": -1},
    ],
)
def test_lesson3_invalid_inputs_do_not_change_state(
    monkeypatch: pytest.MonkeyPatch, arguments: dict[str, int | float]
) -> None:
    monkeypatch.setattr(Lesson3, "count", 8.0)

    async def verify() -> None:
        async with Client(Lesson3.mcp) as client:
            outcome = await client.call_tool("magic", arguments, raise_on_error=False)
            assert outcome.is_error is True

    asyncio.run(verify())
    assert Lesson3.count == 8.0


def test_lesson3_nonfinite_result_is_atomic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Lesson3, "count", 1e308)

    async def verify() -> None:
        async with Client(Lesson3.mcp) as client:
            outcome = await client.call_tool(
                "magic", {"add": 10, "multiply": 1e308, "subtract": 0},
                raise_on_error=False,
            )
            assert outcome.is_error is True

    asyncio.run(verify())
    assert Lesson3.count == 1e308


def test_lesson4_exposes_complete_tool_metadata() -> None:
    async def verify() -> None:
        async with Client(Lesson4.mcp) as client:
            tools = await client.list_tools()
        assert len(tools) == 1
        metadata = tools[0].model_dump(by_alias=True, exclude_none=True)
        assert metadata["name"] == "magic"
        assert metadata["title"] == "Magic Counter - Full MCP Field Demo"
        assert {icon["theme"] for icon in metadata["icons"]} == {"light", "dark"}
        assert set(metadata["inputSchema"]["required"]) == {
            "add", "multiply", "subtract"
        }
        assert set(metadata["outputSchema"]["required"]) == {"before", "after"}
        assert metadata["outputSchema"]["additionalProperties"] is False
        assert metadata["annotations"]["readOnlyHint"] is False
        assert metadata["_meta"]["com.example.fastmcp/lessonNumber"] == 4

    asyncio.run(verify())


def test_lesson4_returns_its_two_field_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Lesson4, "count", 0.0)

    async def verify() -> None:
        async with Client(Lesson4.mcp) as client:
            first = await client.call_tool(
                "magic", {"add": 10, "multiply": 2.0, "subtract": 3}
            )
            second = await client.call_tool(
                "magic", {"add": 4, "multiply": 1.5, "subtract": 1}
            )
        assert first.structured_content == {"before": 0.0, "after": 17.0}
        assert second.structured_content == {"before": 17.0, "after": 30.5}

    asyncio.run(verify())
    assert Lesson4.count == 30.5


def test_lesson4_invalid_result_does_not_mutate_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Lesson4, "count", 1e308)

    async def verify() -> None:
        async with Client(Lesson4.mcp) as client:
            result = await client.call_tool(
                "magic", {"add": 10, "multiply": 1e308, "subtract": 0},
                raise_on_error=False,
            )
            assert result.is_error is True

    asyncio.run(verify())
    assert Lesson4.count == 1e308


def test_lesson5_discovers_all_mcp_component_types() -> None:
    async def verify() -> None:
        async with Client(Lesson5.mcp) as client:
            assert {tool.name for tool in await client.list_tools()} == {
                "probe", "async_probe", "from_constructor"
            }
            assert {str(resource.uri) for resource in await client.list_resources()} == {
                "lesson5://guide"
            }
            assert {str(t.uri_template) for t in await client.list_resource_templates()} == {
                "lesson5://item/{item}"
            }
            assert {prompt.name for prompt in await client.list_prompts()} == {"hint"}

    asyncio.run(verify())


def test_lesson5_calls_tools_resources_and_prompts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Lesson5.audit, "calls", 0)

    async def verify() -> None:
        async with Client(Lesson5.mcp) as client:
            result = await client.call_tool("probe", {"amount": 3, "scale": 1.5})
            echo = await client.call_tool("async_probe", {"word": "ok"})
            constructed = await client.call_tool("from_constructor", {})
            resource = await client.read_resource("lesson5://guide")
            templated = await client.read_resource("lesson5://item/apple")
            prompt = await client.get_prompt("hint", {"topic": "tools"})
        assert result.structured_content == {
            "amount": 3, "scale": 1.5, "note": "demo", "total": 4.5
        }
        assert echo.structured_content == {"result": "async:ok:Lesson 5: FastMCP Kitchen Sink"}
        assert constructed.structured_content == {"result": "constructor-tool-ok"}
        assert isinstance(resource[0], TextResourceContents)
        assert resource[0].text == "Lesson 5 resource reached."
        assert isinstance(templated[0], TextResourceContents)
        assert templated[0].text == "item=apple"
        assert len(prompt.messages) == 1

    asyncio.run(verify())
    assert Lesson5.audit.calls == 3


def test_lesson5_health_route_uses_in_process_http() -> None:
    async def verify() -> None:
        app = Lesson5.mcp.http_app()
        async with app.lifespan(app):
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url="http://local"
            ) as client:
                response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"ok": True, "lesson": 5}

    asyncio.run(verify())


@pytest.mark.parametrize("server", [Lesson5.mcp, Lesson6.mcp])
def test_probe_rejects_negative_amount(server: FastMCP) -> None:
    # Both lessons expose the same validated probe contract.

    async def verify() -> None:
        async with Client(server) as client:
            outcome = await client.call_tool(
                "probe", {"amount": -1}, raise_on_error=False
            )
            assert outcome.is_error is True

    asyncio.run(verify())


def test_lesson6_model_visible_tools_only() -> None:
    async def verify() -> None:
        async with Client(Lesson6.mcp) as client:
            tools = await client.list_tools()
            result = await client.call_tool("probe", {"amount": 4})
            echo = await client.call_tool("async_probe", {"word": "hi"})
            constructor = await client.call_tool("from_constructor", {})
        assert {tool.name for tool in tools} == {
            "probe", "async_probe", "from_constructor"
        }
        assert result.structured_content == {
            "amount": 4, "scale": 2.0, "note": "demo", "total": 8.0
        }
        assert echo.structured_content == {"result": "async:hi:Lesson 6: Model-Visible Only"}
        assert constructor.structured_content == {"result": "constructor-tool-ok"}

    asyncio.run(verify())
