"""Lesson 2 shows real MCP request/response messages without opening a socket."""

import asyncio

import pytest

import Lesson2


def test_mcp_wire_messages(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Lesson2, "count", 0)
    asyncio.run(Lesson2.main())
    output = capsys.readouterr().out
    assert '"method": "initialize"' in output
    assert '"method": "tools/list"' in output
    assert output.count('"method": "tools/call"') == 2
    assert '"name": "increase"' in output
    assert '"result":1' in output
    assert '"result":2' in output
    assert "event: message" in output
    assert Lesson2.count == 2
