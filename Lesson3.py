"""Lesson 3: a standalone stateful MCP tool with a complete output schema."""

import math
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

mcp = FastMCP("Lesson 3: Structured Magic")
count: float = 0


class MagicResult(BaseModel):
    """Exact structure returned by the magic tool."""

    before: float = Field(description="Counter before this call.", examples=[0.0, 17.0, 30.5])
    add: int = Field(description="Unsigned amount added.", examples=[0, 4, 10])
    multiply: float = Field(description="Multiplier applied.", examples=[0.0, 1.5, 2.0])
    subtract: int = Field(description="Unsigned amount subtracted.", examples=[0, 1, 3])
    after: float = Field(description="Counter after this call.", examples=[0.0, 17.0, 30.5])


@mcp.tool(
    title="Magic Counter",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
def magic(
    add: Annotated[int, Field(ge=0, le=4_294_967_295, strict=True,
                              description="Unsigned 32-bit integer to add.",
                              examples=[0, 1, 4, 10, 100, 4_294_967_295])],
    multiply: Annotated[float, Field(allow_inf_nan=False,
                                     description="Finite floating-point multiplier.",
                                     examples=[0.0, 0.5, 1.0, 1.5, 2.0, -1.0])],
    subtract: Annotated[int, Field(ge=0, le=4_294_967_295, strict=True,
                                   description="Unsigned 32-bit integer to subtract.",
                                   examples=[0, 1, 3, 10, 100, 4_294_967_295])],
) -> MagicResult:
    """Update this server's counter: (count + add) * multiply - subtract.

    All inputs are required. add and subtract are unsigned 32-bit integers;
    multiply is a finite number. A negative final counter is allowed.
    The counter survives tool calls but resets when this process restarts.

    Worked examples, in order (start with count = 0):
        magic(add=10, multiply=2.0, subtract=3)
            -> before=0.0, after=17.0
        magic(add=4, multiply=1.5, subtract=1)
            -> before=17.0, after=30.5
        magic(add=0, multiply=1.0, subtract=0)
            -> before=30.5, after=30.5 (no change)
        magic(add=0, multiply=0.0, subtract=0)
            -> before=30.5, after=0.0 (clear counter)
        magic(add=0, multiply=1.0, subtract=7)
            -> before=0.0, after=-7.0 (negative counter is valid)
        magic(add=7, multiply=-2.0, subtract=5)
            -> before=-7.0, after=-5.0 (negative multiplier)

    Example structuredContent for the FIRST call:
        {"before": 0.0, "add": 10, "multiply": 2.0,
         "subtract": 3, "after": 17.0}

    Invalid input examples (rejected before updating count):
        add=-1, subtract=-1, add=4294967296, or multiply=Infinity.
    """
    global count
    before = count
    after = (before + add) * multiply - subtract
    if not math.isfinite(after):
        raise ValueError("Counter would become non-finite")
    count = after
    return MagicResult(before=before, add=add, multiply=multiply,
                       subtract=subtract, after=after)


def main() -> None:
    mcp.run(transport="http", host="127.0.0.1", port=6969)


if __name__ == "__main__":
    main()
