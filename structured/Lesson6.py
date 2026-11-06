"""Lesson 6: Lesson 5 stripped down to the ChatGPT-visible pieces.

    .venv-linux/bin/python Lesson6.py            # inspect MCP tool JSON
    .venv-linux/bin/python Lesson6.py --demo     # three real local calls
    .venv-linux/bin/python Lesson6.py --serve    # localhost:6971

Only server instructions, callable tools, their descriptions, argument
constraints/defaults/examples, and structured results are deliberately authored.
FastMCP may still generate its own default discovery fields.
"""

import argparse
import asyncio
import json

from fastmcp import Client, Context, FastMCP
from pydantic import BaseModel, Field


def from_constructor() -> str:
    """Tool registered via FastMCP(tools=...), without a decorator."""
    return "constructor-tool-ok"


mcp = FastMCP(
    name="Lesson 6: Model-Visible Only",
    instructions="Use probe for multiplication, async_probe for an echo, and from_constructor for a static reply.",
    tools=[from_constructor],
)


class ProbeResult(BaseModel, extra="forbid"):
    """Result fields used only to observe schemas."""

    amount: int = Field(description="Echo amount.", examples=[3, 10])
    scale: float = Field(description="Echo multiplier.", examples=[1.5, 2])
    note: str = Field(description="Echo label.", examples=["hello"])
    total: float = Field(description="Product.", examples=[6, 20])


@mcp.tool
def probe(
    amount: int = Field(ge=0, le=100, strict=True, description="0..100.", examples=[3]),
    scale: float = Field(default=2.0, ge=0, le=10, description="Multiplier.", examples=[2.0]),
    note: str = Field(default="demo", max_length=20, description="Filler.", examples=["hey"]),
) -> ProbeResult:
    """Filler tool. Multiplies amount by scale."""
    return ProbeResult(amount=amount, scale=scale, note=note, total=amount * scale)


@mcp.tool
async def async_probe(ctx: Context, word: str = "hi") -> str:
    """Returns a context-aware reply."""
    return f"async:{word}:{ctx.fastmcp.name}"


async def inspect() -> None:
    """Print real tool discovery plus the server instruction."""
    async with Client(mcp) as client:
        tools = await client.list_tools()
    print(
        json.dumps(
            {
                "server_instructions": mcp.instructions,
                "tools": [
                    tool.model_dump(by_alias=True, exclude_none=True) for tool in tools
                ],
            },
            indent=2,
        )
    )


async def demo() -> None:
    """Call all three tools locally."""
    async with Client(mcp) as client:
        probe_result = await client.call_tool("probe", {"amount": 3})
        echo_result = await client.call_tool("async_probe", {"word": "ok"})
        constructor_result = await client.call_tool("from_constructor", {})
    print(
        json.dumps(
            {
                "probe": probe_result.structured_content,
                "async_probe": [
                    part.model_dump(exclude_none=True) for part in echo_result.content
                ],
                "constructor": [
                    part.model_dump(exclude_none=True)
                    for part in constructor_result.content
                ],
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--demo", action="store_true")
    mode.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    if args.demo:
        asyncio.run(demo())
    elif args.serve:
        mcp.run(transport="http", host="127.0.0.1", port=6969)
    else:
        asyncio.run(inspect())


if __name__ == "__main__":
    main()
