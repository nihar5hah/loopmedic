from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call
from pydantic import ValidationError

from loopmedic.core.trace_store import TraceStore
from loopmedic.environment.seed import write_pristine_db
from loopmedic.environment.service import LEDGER_SUCCEEDED, connect, current_step
from loopmedic.evaluation.scenario import load_scenario
from loopmedic.evaluation.tasks import booking_task
from loopmedic.facade.faults import (
    FaultInjector,
    FaultSpec,
    timeout_payload,
)
from loopmedic.facade.server import make_facade_server
from loopmedic.runner.agent import BookingContext
from loopmedic.runner.config import PROJECT_ROOT
from loopmedic.runner.run import run_task

SCENARIOS = PROJECT_ROOT / "scenarios"


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


def _world(tmp_path: Path, spec: FaultSpec):
    db_path = tmp_path / "world.db"
    write_pristine_db(db_path, seed=42)
    conn = connect(db_path)
    booking = BookingContext(conn=conn, run_id="fault-test")
    store = TraceStore(tmp_path / "trace.db")
    store.start_run(booking.run_id)
    injector = FaultInjector(spec)
    server = make_facade_server(booking, store, injector=injector)
    return conn, booking, store, server


def test_timeout_payloads_are_identical() -> None:
    assert timeout_payload() == {
        "ok": False,
        "code": "timeout",
        "error": "tool call timed out",
    }


def test_pre_execution_timeout_does_not_write(tmp_path: Path) -> None:
    spec = FaultSpec(
        fault_type="pre_execution_timeout",
        target_tool="hold_slot",
        trigger_on_call=1,
        seed=1,
    )
    conn, booking, store, server = _world(tmp_path, spec)
    try:
        before_step = current_step(conn)
        payload = _mcp_payload(
            asyncio.run(
                server.call_tool(
                    "hold_slot",
                    {"customer_id": "C000", "slot_id": "S001"},
                )
            )
        )
        assert payload == timeout_payload()
        assert conn.execute("SELECT COUNT(*) FROM holds").fetchone()[0] == 0
        assert current_step(conn) == before_step
        ledger = conn.execute("SELECT COUNT(*) FROM operation_ledger").fetchone()[0]
        assert ledger == 0
        failed = [
            event
            for event in store.timeline(booking.run_id)
            if event["event_type"] == "tool_failed"
        ]
        assert len(failed) == 1
        assert failed[0]["injected_fault"] == "pre_execution_timeout"
        assert failed[0]["result"] == timeout_payload()
        assert failed[0]["state_hash_before"] == failed[0]["state_hash_after"]
    finally:
        store.close()
        conn.close()


def test_post_commit_loss_commits_then_returns_same_timeout(
    tmp_path: Path,
) -> None:
    spec = FaultSpec(
        fault_type="post_commit_response_loss",
        target_tool="create_appointment",
        trigger_on_call=1,
        seed=2,
    )
    conn, booking, store, server = _world(tmp_path, spec)
    try:
        held = _mcp_payload(
            asyncio.run(
                server.call_tool(
                    "hold_slot",
                    {"customer_id": "C000", "slot_id": "S001"},
                )
            )
        )
        assert held["ok"] is True
        lost = _mcp_payload(
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
        assert lost == timeout_payload()
        retry = _mcp_payload(
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
        assert retry["ok"] is True
        rows = conn.execute(
            """
            SELECT appointment_id, status FROM appointments
            WHERE customer_id = 'C000' AND status = 'CONFIRMED'
            ORDER BY appointment_id
            """
        ).fetchall()
        assert len(rows) == 2
        assert rows[0][0] != rows[1][0]
        ledger = conn.execute(
            """
            SELECT status, fingerprint FROM operation_ledger
            WHERE tool = 'create_appointment'
            ORDER BY step
            """
        ).fetchall()
        assert [row[0] for row in ledger] == [LEDGER_SUCCEEDED, LEDGER_SUCCEEDED]
        assert ledger[0][1] == ledger[1][1]
        failed = [
            event
            for event in store.timeline(booking.run_id)
            if event["event_type"] == "tool_failed"
        ]
        assert len(failed) == 1
        assert failed[0]["injected_fault"] == "post_commit_response_loss"
        assert failed[0]["result"] == timeout_payload()
        assert failed[0]["state_hash_before"] != failed[0]["state_hash_after"]
    finally:
        store.close()
        conn.close()


def test_stale_read_returns_previous_answer(tmp_path: Path) -> None:
    spec = FaultSpec(
        fault_type="stale_read",
        target_tool="list_customer_appointments",
        trigger_on_call=2,
        seed=3,
    )
    conn, booking, store, server = _world(tmp_path, spec)
    try:
        first = _mcp_payload(
            asyncio.run(
                server.call_tool(
                    "list_customer_appointments",
                    {"customer_id": "C000"},
                )
            )
        )
        assert first["ok"] is True
        assert first["appointments"] == []
        held = _mcp_payload(
            asyncio.run(
                server.call_tool(
                    "hold_slot",
                    {"customer_id": "C000", "slot_id": "S001"},
                )
            )
        )
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
        stale = _mcp_payload(
            asyncio.run(
                server.call_tool(
                    "list_customer_appointments",
                    {"customer_id": "C000"},
                )
            )
        )
        assert stale == first
        live_count = conn.execute(
            """
            SELECT COUNT(*) FROM appointments
            WHERE customer_id = 'C000' AND status = 'CONFIRMED'
            """
        ).fetchone()[0]
        assert live_count == 1
        completed = [
            event
            for event in store.timeline(booking.run_id)
            if event["event_type"] == "tool_completed"
            and event["tool_name"] == "list_customer_appointments"
        ]
        assert completed[-1]["injected_fault"] == "stale_read"
    finally:
        store.close()
        conn.close()


def test_transient_error_fails_once_then_succeeds(tmp_path: Path) -> None:
    spec = FaultSpec(
        fault_type="transient_error",
        target_tool="hold_slot",
        trigger_on_call=1,
        seed=4,
    )
    conn, booking, store, server = _world(tmp_path, spec)
    try:
        first = _mcp_payload(
            asyncio.run(
                server.call_tool(
                    "hold_slot",
                    {"customer_id": "C000", "slot_id": "S001"},
                )
            )
        )
        assert first["ok"] is False
        assert first["code"] == "transient_error"
        assert conn.execute("SELECT COUNT(*) FROM holds").fetchone()[0] == 0
        second = _mcp_payload(
            asyncio.run(
                server.call_tool(
                    "hold_slot",
                    {"customer_id": "C000", "slot_id": "S001"},
                )
            )
        )
        assert second["ok"] is True
        assert second["hold_id"]
        assert conn.execute("SELECT COUNT(*) FROM holds").fetchone()[0] == 1
        failed = [
            event
            for event in store.timeline(booking.run_id)
            if event["event_type"] == "tool_failed"
        ]
        assert failed[0]["injected_fault"] == "transient_error"
    finally:
        store.close()
        conn.close()


def test_scripted_retry_after_post_commit_creates_duplicate(
    tmp_path: Path,
) -> None:
    model = ScriptedModel(
        [
            ModelStep(
                output=[
                    function_call(
                        "hold_slot",
                        {"customer_id": "C000", "slot_id": "S001"},
                        call_id="hold-1",
                    )
                ]
            ),
            ModelStep(
                output=[
                    function_call(
                        "create_appointment",
                        {
                            "customer_id": "C000",
                            "slot_id": "S001",
                            "hold_id": "H001",
                        },
                        call_id="create-lost",
                    )
                ]
            ),
            ModelStep(
                output=[
                    function_call(
                        "create_appointment",
                        {
                            "customer_id": "C000",
                            "slot_id": "S001",
                            "hold_id": "H001",
                        },
                        call_id="create-retry",
                    )
                ]
            ),
            ModelStep(
                output=[assistant_message("retried create", item_id="msg-dup")]
            ),
        ]
    )
    loaded = load_scenario(SCENARIOS / "smoke-post-commit-loss.yaml")
    record = run_task(
        booking_task(),
        runs_dir=tmp_path,
        model=model,
        fault=loaded.fault,
    )
    assert record.error is None
    assert record.checks["no_duplicate_booking_final"] is False
    store = TraceStore(record.trace_path)
    timeline = store.timeline(record.run_id)
    store.close()
    started = next(
        event for event in timeline if event["event_type"] == "run_started"
    )
    assert started["result"]["fault"]["fault_type"] == "post_commit_response_loss"
    assert started["result"]["fault"]["seed"] == 2
    creates = [
        event
        for event in timeline
        if event["tool_name"] == "create_appointment"
        and event["event_type"] in {"tool_completed", "tool_failed"}
    ]
    assert len(creates) == 2
    assert creates[0]["event_type"] == "tool_failed"
    assert creates[0]["injected_fault"] == "post_commit_response_loss"
    assert creates[0]["result"] == timeout_payload()
    assert creates[0]["state_hash_before"] != creates[0]["state_hash_after"]
    assert creates[1]["event_type"] == "tool_completed"
    assert creates[1]["result"]["ok"] is True
    assert creates[1]["injected_fault"] is None
    db = connect(tmp_path / f"{record.run_id}.db")
    try:
        appointments = db.execute(
            """
            SELECT appointment_id FROM appointments
            WHERE customer_id = 'C000' AND status = 'CONFIRMED'
            """
        ).fetchall()
        assert len(appointments) == 2
        statuses = db.execute(
            """
            SELECT status FROM operation_ledger
            WHERE tool = 'create_appointment'
            """
        ).fetchall()
        assert [row[0] for row in statuses] == [LEDGER_SUCCEEDED, LEDGER_SUCCEEDED]
    finally:
        db.close()


def _canonical(payload: dict) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _hold_args() -> dict[str, str]:
    return {"customer_id": "C000", "slot_id": "S001"}


def _inject_once(folder: Path, spec: FaultSpec) -> tuple[str, str]:
    folder.mkdir(parents=True, exist_ok=True)
    conn, booking, store, server = _world(folder, spec)
    try:
        if spec.fault_type == "pre_execution_timeout":
            payload = _mcp_payload(
                asyncio.run(server.call_tool("hold_slot", _hold_args()))
            )
        elif spec.fault_type == "post_commit_response_loss":
            held = _mcp_payload(
                asyncio.run(server.call_tool("hold_slot", _hold_args()))
            )
            payload = _mcp_payload(
                asyncio.run(
                    server.call_tool(
                        "create_appointment",
                        {**_hold_args(), "hold_id": held["hold_id"]},
                    )
                )
            )
        elif spec.fault_type == "stale_read":
            asyncio.run(
                server.call_tool(
                    "list_customer_appointments",
                    {"customer_id": "C000"},
                )
            )
            held = _mcp_payload(
                asyncio.run(server.call_tool("hold_slot", _hold_args()))
            )
            asyncio.run(
                server.call_tool(
                    "create_appointment",
                    {**_hold_args(), "hold_id": held["hold_id"]},
                )
            )
            payload = _mcp_payload(
                asyncio.run(
                    server.call_tool(
                        "list_customer_appointments",
                        {"customer_id": "C000"},
                    )
                )
            )
        elif spec.fault_type == "transient_error":
            payload = _mcp_payload(
                asyncio.run(server.call_tool("hold_slot", _hold_args()))
            )
        else:
            raise AssertionError(spec.fault_type)
        injected = next(
            event
            for event in store.timeline(booking.run_id)
            if event["injected_fault"] == spec.fault_type
        )
        return _canonical(payload), injected["state_hash_after"]
    finally:
        store.close()
        conn.close()


def test_faults_reproduce_from_seed(tmp_path: Path) -> None:
    specs = [
        FaultSpec(
            fault_type="pre_execution_timeout",
            target_tool="hold_slot",
            trigger_on_call=1,
            seed=1,
        ),
        FaultSpec(
            fault_type="post_commit_response_loss",
            target_tool="create_appointment",
            trigger_on_call=1,
            seed=2,
        ),
        FaultSpec(
            fault_type="stale_read",
            target_tool="list_customer_appointments",
            trigger_on_call=2,
            seed=3,
        ),
        FaultSpec(
            fault_type="transient_error",
            target_tool="hold_slot",
            trigger_on_call=1,
            seed=4,
        ),
    ]
    for spec in specs:
        first = _inject_once(tmp_path / f"{spec.fault_type}-a", spec)
        second = _inject_once(tmp_path / f"{spec.fault_type}-b", spec)
        assert first[0] == second[0]
        assert first[1] == second[1]


def test_smoke_scenarios_load() -> None:
    loaded = [load_scenario(path) for path in sorted(SCENARIOS.glob("smoke-*.yaml"))]
    names = {item.name: item.fault.fault_type for item in loaded if item.fault}
    assert names == {
        "smoke-pre-execution-timeout": "pre_execution_timeout",
        "smoke-post-commit-loss": "post_commit_response_loss",
        "smoke-stale-read": "stale_read",
        "smoke-transient-error": "transient_error",
    }
    assert all(item.fault is not None and item.fault.seed >= 0 for item in loaded)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        (
            {
                "fault_type": "stale_read",
                "target_tool": "hold_slot",
                "trigger_on_call": 2,
                "seed": 1,
            },
            "read tool",
        ),
        (
            {
                "fault_type": "stale_read",
                "target_tool": "list_customer_appointments",
                "trigger_on_call": 1,
                "seed": 1,
            },
            "trigger_on_call >= 2",
        ),
        (
            {
                "fault_type": "post_commit_response_loss",
                "target_tool": "get_customer",
                "trigger_on_call": 1,
                "seed": 1,
            },
            "write tool",
        ),
        (
            {
                "fault_type": "transient_error",
                "target_tool": "not_a_tool",
                "trigger_on_call": 1,
                "seed": 1,
            },
            "unknown target_tool",
        ),
        (
            {
                "fault_type": "transient_error",
                "target_tool": "hold_slot",
                "trigger_on_call": 16,
                "seed": 1,
            },
            "less than or equal to 15",
        ),
    ],
)
def test_fault_spec_rejects_invalid_config(kwargs: dict, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        FaultSpec(**kwargs)


def test_fault_spec_requires_seed() -> None:
    with pytest.raises(ValidationError):
        FaultSpec(
            fault_type="transient_error",
            target_tool="hold_slot",
            trigger_on_call=1,
        )


def test_stale_read_without_previous_answer_raises() -> None:
    injector = FaultInjector(
        FaultSpec(
            fault_type="stale_read",
            target_tool="list_customer_appointments",
            trigger_on_call=2,
            seed=3,
        )
    )
    injector.consider(
        "list_customer_appointments",
        {"customer_id": "C000"},
        "run-a",
    )
    with pytest.raises(ValueError, match="no previous live answer"):
        injector.consider(
            "list_customer_appointments",
            {"customer_id": "C001"},
            "run-a",
        )


def test_injector_refuses_reuse_across_runs() -> None:
    injector = FaultInjector(
        FaultSpec(
            fault_type="transient_error",
            target_tool="hold_slot",
            trigger_on_call=1,
            seed=4,
        )
    )
    injector.consider("hold_slot", _hold_args(), "run-a")
    with pytest.raises(RuntimeError, match="cannot be reused"):
        injector.consider("hold_slot", _hold_args(), "run-b")


def test_run_task_rejects_trigger_past_cap(tmp_path: Path) -> None:
    spec = FaultSpec(
        fault_type="transient_error",
        target_tool="hold_slot",
        trigger_on_call=2,
        seed=1,
    )
    with pytest.raises(ValueError, match="exceeds tool cap"):
        run_task(booking_task(), runs_dir=tmp_path, cap=1, fault=spec)


def test_load_scenario_rejects_incompatible_fault(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        "\n".join(
            [
                "name: bad",
                "task:",
                "  kind: booking",
                "fault:",
                "  fault_type: stale_read",
                "  target_tool: hold_slot",
                "  trigger_on_call: 2",
                "  seed: 1",
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="read tool"):
        load_scenario(path)
