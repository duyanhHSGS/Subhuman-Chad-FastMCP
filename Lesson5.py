"""Lesson 5: FastMCP kitchen sink. Fill fields; inspect actual discovery.

Run from this folder:
    .venv-linux/bin/python Lesson5.py            # inspect locally
    .venv-linux/bin/python Lesson5.py --demo     # exercise components
    .venv-linux/bin/python Lesson5.py --serve    # 127.0.0.1:6970

FastMCP 4.0.5. Auth is intentionally off; no internet or tunnel is needed.
Empty provider/transform slots demonstrate constructor support, not behavior.
"""

import argparse
import asyncio
import base64
import json
import secrets
from collections.abc import AsyncIterator
from typing import Annotated

import httpx2
from fastmcp import Client, Context, FastMCP
from fastmcp.apps import AppConfig
from fastmcp.server.lifespan import lifespan
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.server.providers.local_provider import LocalProvider
from fastmcp.resources.security import ResourceSecurity
from mcp.server.request_state import RequestStateSecurity
from fastmcp.tools import ToolResult
from mcp.types import Annotations, CallToolRequestParams, Icon, ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import Request
from starlette.responses import JSONResponse


def make_icon(theme: str) -> Icon:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48">'
        '<rect x="2" y="2" width="44" height="44" rx="9" fill="#3268cc"/>'
        '<text x="24" y="30" text-anchor="middle" font-size="22" '
        'fill="white">5</text></svg>'
    )
    encoded = base64.b64encode(svg.encode()).decode("ascii")
    return Icon(
        src=f"data:image/svg+xml;base64,{encoded}",
        mime_type="image/svg+xml",
        sizes=["48x48"],
        theme="light" if theme == "light" else "dark",
    )


ICONS = [make_icon("light"), make_icon("dark")]


class AuditMiddleware(Middleware):
    """Count tool invocations; nothing is written to disk."""

    def __init__(self) -> None:
        self.calls = 0

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        self.calls += 1
        return await call_next(context)


audit = AuditMiddleware()


@lifespan
async def demo_lifespan(_server: FastMCP) -> AsyncIterator[dict[str, str]]:
    """Expose tiny startup context for this lesson."""
    yield {"lesson": "five", "status": "ready"}


def from_constructor() -> str:
    """Tool registered via FastMCP(tools=...), without a decorator."""
    return "constructor-tool-ok"


mcp = FastMCP(
    name="Lesson 5: FastMCP Kitchen Sink",
    instructions="Use probe for filler, read guide for metadata, use prompt for a hint.",
    version="5.0.0",
    website_url="https://example.org/lesson5",
    icons=ICONS,
    auth=None,  # Deliberately public ON LOOPBACK ONLY.
    middleware=[audit],
    providers=[LocalProvider()],
    transforms=[],
    lifespan=demo_lifespan,
    tools=[from_constructor],
    on_duplicate="error",
    mask_error_details=True,
    dereference_schemas=True,
    strict_input_validation=True,
    list_page_size=25,
    resource_security=ResourceSecurity(),
    request_state_security=RequestStateSecurity(keys=[secrets.token_bytes(32)]),
    cache_ttl=30,
    cache_scope="private",
    tasks=False,  # No optional task backend required.
    session_state_store=None,
    client_log_level="info",
    experimental_capabilities={
        "com.example.lesson5/demo": {"feature": "filler", "enabled": True}
    },
)


class ProbeResult(BaseModel):
    """Result fields used only to observe schemas."""

    model_config = ConfigDict(extra="forbid")

    amount: int = Field(description="Echo amount.", examples=[3, 10])
    scale: float = Field(description="Echo multiplier.", examples=[1.5, 2])
    note: str = Field(description="Echo label.", examples=["hello"])
    total: float = Field(description="Product.", examples=[6, 20])


@mcp.tool(
    name="probe",
    version="5",
    title="The Fully Decorated Probe",
    description="Filler tool. Multiplies amount by scale.",
    icons=ICONS,
    tags={"lesson5", "math", "filler"},
    output_schema=ProbeResult.model_json_schema(),
    annotations=ToolAnnotations(
        title="Probe arithmetic",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
    meta={
        "com.example.lesson5/id": 5,
        "com.example.lesson5/filler": {"alpha": 1, "beta": True},
    },
    app=AppConfig(visibility=["model"], prefers_border=True),
    task=False,
    timeout=10.0,
    auth=None,
    run_in_thread=True,
)
def probe(
    amount: Annotated[
        int, Field(ge=0, le=100, strict=True, description="0..100.", examples=[3])
    ],
    scale: Annotated[
        float, Field(ge=0, le=10, description="Multiplier.", examples=[2.0])
    ] = 2.0,
    note: Annotated[
        str, Field(max_length=20, description="Filler.", examples=["hey"])
    ] = "demo",
) -> ProbeResult:
    """Expose everything the tool decorator supports without side effects."""
    return ProbeResult(amount=amount, scale=scale, note=note, total=amount * scale)


@mcp.tool(
    name="async_probe",
    version="1",
    title="Async Context Demo",
    description="Returns a context-aware reply.",
    tags={"lesson5", "async"},
    task=False,
    run_in_thread=False,
)
async def async_probe(ctx: Context, word: str = "hi") -> str:
    """Demonstrate async tools and FastMCP context injection."""
    return f"async:{word}:{ctx.fastmcp.name}"


@mcp.resource(
    "lesson5://guide",
    name="guide",
    version="5",
    title="Lesson 5 Guide",
    description="Static filler resource.",
    icons=ICONS,
    mime_type="text/plain",
    tags={"lesson5", "docs"},
    annotations=Annotations(audience=["assistant"], priority=0.8),
    meta={"com.example.lesson5/kind": "resource"},
    app={"visibility": ["model"]},
    auth=None,
    security=ResourceSecurity(),
)
def guide() -> str:
    """Small resource exposed via MCP resources/list."""
    return "Lesson 5 resource reached."


@mcp.resource(
    "lesson5://item/{item}",
    name="item",
    title="Item Template",
    description="Filler URI template.",
    mime_type="text/plain",
    tags={"lesson5"},
)
def item_resource(item: str) -> str:
    """Demonstrate resource templates with parameters."""
    return f"item={item}"


@mcp.prompt(
    name="hint",
    version="5",
    title="Lesson 5 Hint",
    description="Short prompt with one argument.",
    icons=ICONS,
    tags={"lesson5"},
    meta={"com.example.lesson5/kind": "prompt"},
    auth=None,
)
def hint(topic: str = "FastMCP") -> str:
    """Create a tiny user prompt."""
    return f"Inspect {topic} components."


@mcp.custom_route("/health", methods=["GET"], name="lesson5-health")
async def health(_request: Request) -> JSONResponse:
    """A regular HTTP route, NOT an MCP tool."""
    return JSONResponse({"ok": True, "lesson": 5})


def as_json(value: object) -> object:
    """Normalize typed MCP models for truthful JSON printing."""
    if isinstance(value, BaseModel):
        return value.model_dump(by_alias=True, exclude_none=True)
    return value


async def inspect() -> None:
    """Print actual MCP client discovery, not guessed JSON."""
    async with Client(mcp) as client:
        packet = {
            "server_identity_from_python": {
                "name": mcp.name,
                "version": mcp.version,
                "instructions": mcp.instructions,
                "website_url": mcp.website_url,
                "icons": [as_json(x) for x in mcp.icons],
            },
            "tools": [as_json(x) for x in await client.list_tools()],
            "resources": [as_json(x) for x in await client.list_resources()],
            "templates": [as_json(x) for x in await client.list_resource_templates()],
            "prompts": [as_json(x) for x in await client.list_prompts()],
        }
    print(json.dumps(packet, indent=2))


async def demo() -> None:
    """Execute real local calls and the custom HTTP route."""
    async with Client(mcp) as client:
        first = await client.call_tool("probe", {"amount": 3, "note": "demo"})
        second = await client.call_tool("async_probe", {"word": "ok"})
        third = await client.call_tool("from_constructor", {})
        static = await client.read_resource("lesson5://guide")
        template = await client.read_resource("lesson5://item/apple")
        rendered = await client.get_prompt("hint", {"topic": "tools"})
    app = mcp.http_app()
    async with app.lifespan(app):
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://local"
        ) as client:
            response = await client.get("/health")
    print(
        json.dumps(
            {
                "probe": first.structured_content,
                "async_probe": [as_json(x) for x in second.content],
                "constructor": [as_json(x) for x in third.content],
                "resource": [as_json(x) for x in static],
                "template": [as_json(x) for x in template],
                "prompt": as_json(rendered),
                "health": response.json(),
                "middleware_tool_calls": audit.calls,
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--demo", action="store_true", help="Run local calls")
    mode.add_argument("--serve", action="store_true", help="Bind localhost:6970")
    args = parser.parse_args()
    if args.demo:
        asyncio.run(demo())
    elif args.serve:
        mcp.run(transport="http", host="127.0.0.1", port=6969)
    else:
        asyncio.run(inspect())


if __name__ == "__main__":
    main()
