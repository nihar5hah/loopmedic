from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from loopmedic.environment.mcp_server import TOOL_NAMES, make_appointment_server
from loopmedic.environment.seed import write_pristine_db
from loopmedic.environment.service import (
    DomainError,
    BOOKING_POLICY,
    cancel_appointment,
    connect,
    create_appointment,
    current_step,
    get_booking_policy,
    get_customer,
    hold_slot,
    list_customer_appointments,
    operation_fingerprint,
    release_hold,
    search_available_slots,
    send_confirmation,
)
from loopmedic.evaluation.invariants import evaluate
from loopmedic.evaluation.tasks import TaskSpec, reschedule_task

RUN_ID = "phase1-test"


@pytest.fixture
def conn(tmp_path: Path):
    path = tmp_path / "world.db"
    write_pristine_db(path, seed=42)
    db = connect(path)
    try:
        yield db
    finally:
        db.close()


def _fp(tool: str, *parts: str) -> str:
    return operation_fingerprint(RUN_ID, tool, *parts)


def _hold_then_create(conn, slot_id: str, attempt_suffix: str):
    hold = hold_slot(
        conn,
        "C001",
        slot_id,
        f"att-hold-{attempt_suffix}",
        _fp("hold_slot", "C001", slot_id),
    )
    created = create_appointment(
        conn,
        "C001",
        slot_id,
        hold["hold_id"],
        f"att-create-{attempt_suffix}",
        _fp("create_appointment", "C001", slot_id),
    )
    return hold, created


def test_reads_advance_the_logical_clock(conn) -> None:
    assert current_step(conn) == 0
    customer = get_customer(conn, "C001")
    assert customer["customer_id"] == "C001"
    assert current_step(conn) == 1
    policy = get_booking_policy(conn)
    assert policy["policy"] == BOOKING_POLICY
    assert current_step(conn) == 2


def test_double_create_appointment_succeeds(conn) -> None:
    slots = search_available_slots(
        conn,
        day="Wednesday",
        period="afternoon",
    )
    slot_id = slots["slots"][0]["slot_id"]
    hold, first = _hold_then_create(conn, slot_id, "a")
    second = create_appointment(
        conn,
        "C001",
        slot_id,
        hold["hold_id"],
        "att-create-b",
        _fp("create_appointment", "C001", slot_id),
    )
    assert first["appointment_id"] != second["appointment_id"]
    assert first["status"] == "CONFIRMED"
    assert second["status"] == "CONFIRMED"
    remaining = conn.execute(
        "SELECT released FROM holds WHERE hold_id = ?",
        (hold["hold_id"],),
    ).fetchone()
    assert int(remaining[0]) == 0
    appts = list_customer_appointments(conn, "C001")["appointments"]
    confirmed = [row for row in appts if row["status"] == "CONFIRMED"]
    assert len(confirmed) == 3  # seed A001 plus two new ones


def test_aborted_create_is_atomic(conn) -> None:
    slots = search_available_slots(
        conn,
        day="Wednesday",
        period="afternoon",
    )
    slot_id = slots["slots"][0]["slot_id"]
    hold = hold_slot(
        conn,
        "C001",
        slot_id,
        "att-hold",
        _fp("hold_slot", "C001", slot_id),
    )
    create_appointment(
        conn,
        "C001",
        slot_id,
        hold["hold_id"],
        "att-create-abort",
        _fp("create_appointment", "C001", slot_id),
        autocommit=False,
    )
    open_appts = conn.execute(
        "SELECT COUNT(*) FROM appointments WHERE status = 'CONFIRMED'"
    ).fetchone()[0]
    open_ledger = conn.execute(
        "SELECT COUNT(*) FROM operation_ledger WHERE tool = 'create_appointment'"
    ).fetchone()[0]
    assert open_appts == 2  # seed + uncommitted create visible in this txn
    assert open_ledger == 1
    conn.rollback()
    assert conn.execute(
        "SELECT COUNT(*) FROM appointments WHERE status = 'CONFIRMED'"
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM operation_ledger WHERE tool = 'create_appointment'"
    ).fetchone()[0] == 0


def test_scripted_reschedule_passes_invariants(conn) -> None:
    spec = reschedule_task()
    get_customer(conn, spec.customer_id)
    list_customer_appointments(conn, spec.customer_id)
    slots = search_available_slots(
        conn,
        day=spec.requested_day,
        period=spec.requested_period,
    )
    slot_id = slots["slots"][0]["slot_id"]
    hold = hold_slot(
        conn,
        spec.customer_id,
        slot_id,
        "att-hold",
        _fp("hold_slot", spec.customer_id, slot_id),
    )
    created = create_appointment(
        conn,
        spec.customer_id,
        slot_id,
        hold["hold_id"],
        "att-create",
        _fp("create_appointment", spec.customer_id, slot_id),
    )
    cancel_appointment(
        conn,
        spec.original_appointment_id,
        "att-cancel",
        _fp("cancel_appointment", spec.original_appointment_id),
    )
    send_confirmation(
        conn,
        created["appointment_id"],
        "att-confirm",
        _fp("send_confirmation", created["appointment_id"]),
    )
    result = evaluate(conn, spec)
    assert result.checks == {name: True for name in spec.required_invariants}
    assert result.passed


def test_cancel_expected_version_is_optional(conn) -> None:
    with pytest.raises(DomainError) as mismatch:
        cancel_appointment(
            conn,
            "A001",
            "att-cancel-bad",
            _fp("cancel_appointment", "A001"),
            expected_version=99,
        )
    assert mismatch.value.code == "version_mismatch"
    cancelled = cancel_appointment(
        conn,
        "A001",
        "att-cancel-ok",
        _fp("cancel_appointment", "A001"),
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["version"] == 2


def test_expired_hold_cannot_create(conn) -> None:
    slots = search_available_slots(conn, day="Friday", period="morning")
    slot_id = slots["slots"][0]["slot_id"]
    hold = hold_slot(
        conn,
        "C001",
        slot_id,
        "att-hold-ttl",
        _fp("hold_slot", "C001", slot_id),
        ttl_steps=2,
    )
    get_customer(conn, "C001")
    with pytest.raises(DomainError) as expired:
        create_appointment(
            conn,
            "C001",
            slot_id,
            hold["hold_id"],
            "att-create-expired",
            _fp("create_appointment", "C001", slot_id),
        )
    assert expired.value.code == "hold_inactive"


def test_create_fingerprint_ignores_hold_id(conn) -> None:
    slots = search_available_slots(
        conn,
        day="Wednesday",
        period="afternoon",
    )
    slot_id = slots["slots"][0]["slot_id"]
    fingerprint = _fp("create_appointment", "C001", slot_id)
    first_hold = hold_slot(
        conn,
        "C001",
        slot_id,
        "att-hold-1",
        _fp("hold_slot", "C001", slot_id),
    )
    second_hold = hold_slot(
        conn,
        "C001",
        slot_id,
        "att-hold-2",
        _fp("hold_slot", "C001", slot_id),
    )
    assert first_hold["hold_id"] != second_hold["hold_id"]
    first = create_appointment(
        conn,
        "C001",
        slot_id,
        first_hold["hold_id"],
        "att-create-1",
        fingerprint,
    )
    second = create_appointment(
        conn,
        "C001",
        slot_id,
        second_hold["hold_id"],
        "att-create-2",
        fingerprint,
    )
    assert first["appointment_id"] != second["appointment_id"]
    rows = conn.execute(
        """
        SELECT fingerprint FROM operation_ledger
        WHERE tool = 'create_appointment'
        ORDER BY step
        """
    ).fetchall()
    assert [row[0] for row in rows] == [fingerprint, fingerprint]


def test_release_hold_rejects_second_release(conn) -> None:
    slots = search_available_slots(conn, day="Friday", period="afternoon")
    slot_id = slots["slots"][0]["slot_id"]
    hold = hold_slot(
        conn,
        "C001",
        slot_id,
        "att-hold-rel",
        _fp("hold_slot", "C001", slot_id),
    )
    released = release_hold(
        conn,
        hold["hold_id"],
        "att-release-1",
        _fp("release_hold", hold["hold_id"]),
    )
    assert released["released"] == 1
    with pytest.raises(DomainError) as already:
        release_hold(
            conn,
            hold["hold_id"],
            "att-release-2",
            _fp("release_hold", hold["hold_id"]),
        )
    assert already.value.code == "hold_released"


def test_booking_policy_text_is_stable(conn) -> None:
    result = get_booking_policy(conn)
    assert result["policy"] == BOOKING_POLICY
    assert "Creating an appointment does not consume the hold." in result["policy"]


def test_send_confirmation_requires_appointment(conn) -> None:
    with pytest.raises(DomainError) as missing:
        send_confirmation(
            conn,
            "A999",
            "att-confirm-missing",
            _fp("send_confirmation", "A999"),
        )
    assert missing.value.code == "not_found"


def test_mcp_server_exposes_ten_tools(conn) -> None:
    server = make_appointment_server(conn, run_id=RUN_ID)
    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}
    assert names == set(TOOL_NAMES)


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


def test_mcp_server_invokes_read_and_write(conn) -> None:
    server = make_appointment_server(conn, run_id=RUN_ID)
    read = _mcp_payload(
        asyncio.run(server.call_tool("get_customer", {"customer_id": "C001"}))
    )
    assert read["ok"] is True
    assert read["customer_id"] == "C001"
    held = _mcp_payload(
        asyncio.run(
            server.call_tool(
                "hold_slot",
                {"customer_id": "C000", "slot_id": "S001"},
            )
        )
    )
    assert held["ok"] is True
    assert held["hold_id"]
    missing = _mcp_payload(
        asyncio.run(
            server.call_tool("get_customer", {"customer_id": "NOPE"})
        )
    )
    assert missing["ok"] is False
    assert missing["code"] == "not_found"
    assert current_step(conn) == 3


def test_original_appointment_id_defaults_to_none() -> None:
    spec = TaskSpec(
        goal_text="Book a new appointment.",
        customer_id="C000",
        requested_day="Monday",
        requested_period="morning",
        required_invariants=["exactly_one_active_appointment"],
        scenario_seed=1,
    )
    assert spec.original_appointment_id is None
    assert reschedule_task().original_appointment_id == "A001"
