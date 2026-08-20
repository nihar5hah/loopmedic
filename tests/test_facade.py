from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from mcp.shared.exceptions import MCPError

from loopmedic.core.trace_store import TraceStore
from loopmedic.environment.mcp_server import TOOL_NAMES
from loopmedic.environment.seed import write_pristine_db
from loopmedic.environment.service import connect, current_step, operation_fingerprint
from loopmedic.facade.policy import Allow, Block, InterventionPolicy
from loopmedic.facade.server import make_facade_server
from loopmedic.runner.agent import BookingContext
from loopmedic.runner.config import ToolBudgetExceeded


def _mcp_payload(result: object) -> dict:
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        inner = structured.get("result", structured)
        if isinstance(inner, dict):
            return inner
        return structured
    content = getattr(result, "content", None)
    if content:
        text = getattr(content[0], "text", None)
        if isinstance(text, str):
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
    if isinstance(result, dict):
        return result
    raise AssertionError(f"unrecognized MCP result {result!r}")


class BlockHolds:
    def decide(self, pre_event, run_state) -> Allow | Block:
        del run_state
        if pre_event.tool_name == "hold_slot":
            return Block("holds are frozen for this test")
        return Allow()


class BoomPolicy:
    def decide(self, pre_event, run_state) -> Allow | Block:
        del pre_event, run_state
        raise RuntimeError("injected boom")


@pytest.fixture
def facade_world(tmp_path: Path):
    db_path = tmp_path / "world.db"
    write_pristine_db(db_path, seed=42)
    conn = connect(db_path)
    booking = BookingContext(conn=conn, run_id="facade-test")
    store = TraceStore(tmp_path / "trace.db")
    store.start_run(booking.run_id)
    try:
        yield conn, booking, store
    finally:
        store.close()
        conn.close()


def _server(world, policy: InterventionPolicy | None = None):
    conn, booking, store = world
    del conn
    return make_facade_server(booking, store, policy)


def test_facade_exposes_ten_tools(facade_world) -> None:
    server = _server(facade_world)
    tools = asyncio.run(server.list_tools())
    assert {tool.name for tool in tools} == set(TOOL_NAMES)


def test_always_allow_read_emits_hashed_facade_events(facade_world) -> None:
    conn, booking, store = facade_world
    server = _server(facade_world)
    payload = _mcp_payload(
        asyncio.run(server.call_tool("get_customer", {"customer_id": "C000"}))
    )
    assert payload["ok"] is True
    assert payload["customer_id"] == "C000"
    timeline = store.timeline(booking.run_id)
    types = [event["event_type"] for event in timeline]
    assert types == ["tool_proposed", "tool_completed"]
    proposed, completed = timeline
    assert proposed["source"] == "facade"
    assert completed["source"] == "facade"
    assert proposed["tool_name"] == "get_customer"
    assert proposed["arguments"] == {"customer_id": "C000"}
    assert proposed["state_hash_before"]
    assert completed["state_hash_before"] == proposed["state_hash_before"]
    assert completed["state_hash_after"]
    assert completed["result"]["ok"] is True
    assert current_step(conn) == 1


def test_block_does_not_mutate_domain(facade_world) -> None:
    conn, booking, store = facade_world
    before_holds = conn.execute("SELECT COUNT(*) FROM holds").fetchone()[0]
    before_step = current_step(conn)
    server = _server(facade_world, BlockHolds())
    payload = _mcp_payload(
        asyncio.run(
            server.call_tool(
                "hold_slot",
                {"customer_id": "C000", "slot_id": "S001"},
            )
        )
    )
    assert payload["ok"] is False
    assert payload["code"] == "blocked"
    assert conn.execute("SELECT COUNT(*) FROM holds").fetchone()[0] == before_holds
    assert current_step(conn) == before_step
    assert booking.tool_calls == 1
    timeline = store.timeline(booking.run_id)
    types = [event["event_type"] for event in timeline]
    assert types == ["tool_proposed", "intervention", "tool_failed"]
    assert all(event["source"] == "facade" for event in timeline)
    assert timeline[-1]["result"]["code"] == "blocked"


def test_create_appointment_fingerprint_omits_hold_id(facade_world) -> None:
    conn, booking, store = facade_world
    del store
    server = _server(facade_world)
    held = _mcp_payload(
        asyncio.run(
            server.call_tool(
                "hold_slot",
                {"customer_id": "C000", "slot_id": "S001"},
            )
        )
    )
    assert held["ok"] is True
    created = _mcp_payload(
        asyncio.run(
            server.call_tool(
                "create_appointment",
                {
                    "customer_id": "C000",
                    "slot_id": "S001",
                    "hold_id": held["hold_id"],
                },
            )
        )
    )
    assert created["ok"] is True
    fingerprint = conn.execute(
        """
        SELECT fingerprint FROM operation_ledger
        WHERE tool = 'create_appointment'
        """
    ).fetchone()[0]
    expected = operation_fingerprint(
        booking.run_id,
        "create_appointment",
        "C000",
        "S001",
    )
    with_hold = operation_fingerprint(
        booking.run_id,
        "create_appointment",
        "C000",
        "S001",
        held["hold_id"],
    )
    assert fingerprint == expected
    assert fingerprint != with_hold


def test_cap_emits_tool_failed_then_aborts(facade_world) -> None:
    conn, booking, store = facade_world
    del conn
    booking.cap = 1
    server = _server(facade_world)
    first = _mcp_payload(
        asyncio.run(server.call_tool("get_customer", {"customer_id": "C000"}))
    )
    assert first["ok"] is True
    with pytest.raises((MCPError, ToolBudgetExceeded)) as raised:
        asyncio.run(server.call_tool("get_customer", {"customer_id": "C000"}))
    assert "cap 1 exceeded" in str(raised.value)
    timeline = store.timeline(booking.run_id)
    types = [event["event_type"] for event in timeline]
    assert types.count("tool_proposed") == 2
    assert types.count("tool_completed") == 1
    assert types.count("tool_failed") == 1
    failed = next(event for event in timeline if event["event_type"] == "tool_failed")
    assert failed["source"] == "facade"
    assert failed["result"]["code"] == "tool_budget_exceeded"
    assert failed["state_hash_after"]
    assert booking.tool_calls == 2


def test_unexpected_handler_error_is_returned_not_raised(facade_world) -> None:
    conn, booking, store = facade_world
    server = _server(facade_world, BoomPolicy())
    payload = _mcp_payload(
        asyncio.run(server.call_tool("get_customer", {"customer_id": "C000"}))
    )
    assert payload["ok"] is False
    assert payload["code"] == "facade_error"
    assert "injected boom" in payload["error"]
    assert current_step(conn) == 0
    assert booking.tool_calls == 1
    timeline = store.timeline(booking.run_id)
    types = [event["event_type"] for event in timeline]
    assert types == ["tool_proposed", "tool_failed"]
    assert timeline[-1]["source"] == "facade"
    assert timeline[-1]["state_hash_after"]
