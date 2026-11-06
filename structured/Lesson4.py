"""Lesson 4: expose EVERY named MCP Tool field (2026-07-28 core).

Progression from Lesson3.py:
    name           -> explicit tool identifier
    title          -> human-friendly display name
    description    -> task guidance and examples
    icons          -> self-contained light/dark UI icons
    inputSchema    -> generated from annotated function parameters
    outputSchema   -> explicit JSON Schema from a Pydantic result model
    annotations    -> all five standard behavioral hints
    _meta          -> namespaced, machine-readable extension metadata

The specification allows more metadata and future extensions: a literal
"no other fields can ever exist" promise would be incorrect.

Run:
    .venv-linux/bin/python Lesson4.py --inspect  # print actual MCP descriptor
    .venv-linux/bin/python Lesson4.py --demo     # perform two local tool calls
    .venv-linux/bin/python Lesson4.py            # serve MCP on loopback
"""

import argparse
import asyncio
import base64
import json
import math
from typing import Annotated

from fastmcp import Client, FastMCP
from mcp.types import Icon, ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

mcp = FastMCP(
    "Lesson 4: Fully Described Tool",
    instructions=(
        "This lesson exposes one stateful arithmetic counter. Discover the magic "
        "tool, read its description and schemas, then call it only when the user "
        "wants to update the counter. The counter resets on server restart."
    ),
)
count: float = 0


class MagicResult(BaseModel):
    """Complete structured result; unspecified output fields are forbidden."""

    model_config = ConfigDict(extra="forbid")

    before: float = Field(description="Counter before this call.", examples=[0.0, 17.0])
    after: float = Field(description="New counter value.", examples=[17.0, 30.5])


def icon_for(theme: str, fill: str) -> Icon:
    """Build a local data-URI icon; no remote image request is needed."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" '
        'viewBox="0 0 48 48">'
        f'<circle cx="24" cy="24" r="20" fill="{fill}"/>'
        '<path d="M24 9 L29 20 L40 24 L29 29 L24 40 L19 29 L8 24 '
        'L19 20 Z" fill="#ffffff"/></svg>'
    )
    data = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return Icon(
        src=f"data:image/svg+xml;base64,{data}",
        mime_type="image/svg+xml",
        sizes=["48x48"],
        theme="light" if theme == "light" else "dark",
    )


TOOL_DESCRIPTION = """Update a stateful arithmetic counter.

Use this tool ONLY when the user asks to change the counter.
Equation: after = (before + add) * multiply - subtract.
All three arguments are required; add and subtract are unsigned 32-bit
integers, and multiply must be finite. Results may be negative.
The counter persists between calls within this process, but not restarts.

Examples (starting with count=0):
- magic(add=10, multiply=2.0, subtract=3) -> before=0, after=17.
- magic(add=4, multiply=1.5, subtract=1) -> before=17, after=30.5.
- magic(add=0, multiply=1.0, subtract=0) -> current value unchanged.
- magic(add=0, multiply=0.0, subtract=0) -> resets the counter to zero.

Invalid inputs (such as add=-1, subtract=4294967296, or Infinity)
are rejected; a non-finite computed result is rejected before updating.
Side effect: this changes in-memory server state. It cannot inspect files,
run shell commands, control other computers, or access the internet.
"""


@mcp.tool(
    name="magic",
    title="Magic Counter - Full MCP Field Demo",
    description=TOOL_DESCRIPTION,
    icons=[icon_for("light", "#174ea6"), icon_for("dark", "#9b72cb")],
    output_schema=MagicResult.model_json_schema(),
    annotations=ToolAnnotations(
        title="Update counter",
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=False,
    ),
    meta={
        "com.example.fastmcp/lessonNumber": 4,
        "com.example.fastmcp/purpose": "Demonstrate every named core Tool field",
        "com.example.fastmcp/stateLifetime": "in-process",
    },
)
def magic(
    add: Annotated[
        int,
        Field(
            ge=0,
            le=4_294_967_295,
            strict=True,
            description="Unsigned 32-bit amount to add to the counter.",
            examples=[0, 4, 10, 4_294_967_295],
        ),
    ],
    multiply: Annotated[
        float,
        Field(
            allow_inf_nan=False,
            description="Finite multiplier; negative values are allowed.",
            examples=[-2.0, 0.0, 1.0, 1.5, 2.0],
        ),
    ],
    subtract: Annotated[
        int,
        Field(
            ge=0,
            le=4_294_967_295,
            strict=True,
            description="Unsigned 32-bit amount to subtract.",
            examples=[0, 1, 3, 4_294_967_295],
        ),
    ],
) -> MagicResult:
    """Apply one counter update only after validating the final value."""
    global count
    before = count
    after = (before + add) * multiply - subtract
    if not math.isfinite(after):
        raise ValueError("Computed counter is not finite; state was not changed.")
    count = after
    return MagicResult(before=before, after=after)


async def inspect() -> None:
    """Print the real descriptor received by an in-process MCP client."""
    async with Client(mcp) as client:
        descriptors = await client.list_tools()
    for descriptor in descriptors:
        print(
            json.dumps(
                descriptor.model_dump(by_alias=True, exclude_none=True), indent=2
            )
        )


async def demo() -> None:
    """Make two actual MCP tool calls; no network listener or persistent data."""
    async with Client(mcp) as client:
        for arguments in (
            {"add": 10, "multiply": 2.0, "subtract": 3},
            {"add": 4, "multiply": 1.5, "subtract": 1},
        ):
            result = await client.call_tool("magic", arguments)
            print(json.dumps(result.structured_content, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--inspect", action="store_true", help="Print actual MCP Tool JSON"
    )
    mode.add_argument("--demo", action="store_true", help="Call the tool twice locally")
    arguments = parser.parse_args()
    if arguments.inspect:
        asyncio.run(inspect())
    elif arguments.demo:
        asyncio.run(demo())
    else:
        mcp.run(transport="http", host="127.0.0.1", port=6969)


if __name__ == "__main__":
    main()
