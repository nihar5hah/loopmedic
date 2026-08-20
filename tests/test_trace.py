from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from loopmedic.core.trace_store import TraceStore
from loopmedic.evaluation.tasks import booking_task
from loopmedic.facade.policy import Allow, Block
from loopmedic.runner.run import run_task


def _timeline(record):
    store = TraceStore(record.trace_path)
    timeline = store.timeline(record.run_id)
    snapshots = store.list_snapshots(record.run_id)
    store.close()
    return timeline, snapshots


def test_scripted_run_replays_from_trace_db(tmp_path: Path) -> None:
    model = ScriptedModel(
        [
            ModelStep(
                output=[
                    function_call(
                        "get_customer",
                        {"customer_id": "C000"},
                        call_id="call-1",
                    )
                ]
            ),
            ModelStep(
                output=[
                    assistant_message(
                        "Looked up C000.",
                        item_id="msg-2",
                    )
                ]
            ),
        ]
    )
    record = run_task(booking_task(), runs_dir=tmp_path, model=model)
    assert record.trace_path is not None
    timeline, _ = _timeline(record)
    types = [event["event_type"] for event in timeline]
    assert types[0] == "run_started"
    assert types[-1] == "run_completed"
    assert "llm_started" in types
    assert "llm_completed" in types
    assert types.count("tool_proposed") == 1
    assert types.count("tool_completed") == 1
    assert "final_output_proposed" in types
    proposed = next(
        event for event in timeline if event["event_type"] == "tool_proposed"
    )
    completed = next(
        event for event in timeline if event["event_type"] == "tool_completed"
    )
    assert proposed["source"] == "facade"
    assert proposed["state_hash_before"]
    assert completed["source"] == "facade"
    assert completed["tool_name"] == "get_customer"
    assert completed["arguments"] == {"customer_id": "C000"}
    assert completed["state_hash_before"] == proposed["state_hash_before"]
    assert completed["state_hash_after"]
    assert completed["result"]["ok"] is True
    assert completed["result"]["customer_id"] == "C000"
    assert record.history_checks["never_two_active_appointments"] is True
    assert record.error is None


def test_domain_failure_is_tool_failed(tmp_path: Path) -> None:
    model = ScriptedModel(
        [
            ModelStep(
                output=[
                    function_call(
                        "get_customer",
                        {"customer_id": "NOPE"},
                        call_id="call-missing",
                    )
                ]
            ),
            ModelStep(
                output=[
                    assistant_message("missing", item_id="msg-missing")
                ]
            ),
        ]
    )
    record = run_task(booking_task(), runs_dir=tmp_path, model=model)
    timeline, _ = _timeline(record)
    failed = [
        event for event in timeline if event["event_type"] == "tool_failed"
    ]
    assert len(failed) == 1
    assert failed[0]["source"] == "facade"
    assert failed[0]["tool_name"] == "get_customer"
    assert failed[0]["result"]["ok"] is False
    assert failed[0]["result"]["code"] == "not_found"
    assert failed[0]["state_hash_after"]


def test_raised_tool_call_emits_terminal_tool_failed(tmp_path: Path) -> None:
    model = ScriptedModel(
        [
            ModelStep(
                output=[
                    function_call(
                        "get_customer",
                        {"customer_id": "C000"},
                        call_id="call-ok",
                    )
                ]
            ),
            ModelStep(
                output=[
                    function_call(
                        "get_customer",
                        {"customer_id": "C000"},
                        call_id="call-over-cap",
                    )
                ]
            ),
        ]
    )
    record = run_task(booking_task(), runs_dir=tmp_path, model=model, cap=1)
    assert record.error is not None
    assert "cap 1 exceeded" in record.error
    timeline, _ = _timeline(record)
    types = [event["event_type"] for event in timeline]
    assert types.count("tool_proposed") == 2
    assert types.count("tool_completed") == 1
    assert types.count("tool_failed") == 1
    assert types[-1] == "run_completed"
    failed = next(
        event for event in timeline if event["event_type"] == "tool_failed"
    )
    assert failed["source"] == "facade"
    assert failed["tool_name"] == "get_customer"
    assert failed["error"]
    assert failed["state_hash_after"]
    proposed_ids = [
        event["event_id"]
        for event in timeline
        if event["event_type"] == "tool_proposed"
    ]
    assert len(proposed_ids) == 2


def test_same_turn_writes_are_serialized_in_snapshots(tmp_path: Path) -> None:
    model = ScriptedModel(
        [
            ModelStep(
                output=[
                    function_call(
                        "hold_slot",
                        {"customer_id": "C000", "slot_id": "S001"},
                        call_id="hold-1",
                    ),
                    function_call(
                        "hold_slot",
                        {"customer_id": "C000", "slot_id": "S002"},
                        call_id="hold-2",
                    ),
                ]
            ),
            ModelStep(
                output=[assistant_message("held both", item_id="msg-holds")]
            ),
        ]
    )
    record = run_task(booking_task(), runs_dir=tmp_path, model=model)
    timeline, snapshots = _timeline(record)
    completed = [
        event for event in timeline if event["event_type"] == "tool_completed"
    ]
    assert [event["tool_name"] for event in completed] == [
        "hold_slot",
        "hold_slot",
    ]
    assert completed[0]["state_hash_after"] != completed[1]["state_hash_after"]
    hold_counts = [
        len(snapshot.holds) for snapshot in snapshots if snapshot.holds
    ]
    assert 1 in hold_counts
    assert hold_counts[-1] == 2
    assert record.error is None


class _BoomPolicy:
    def decide(self, pre_event, run_state) -> Allow | Block:
        del pre_event, run_state
        raise RuntimeError("injected boom")


def test_recoverable_facade_error_does_not_abort_the_run(tmp_path: Path) -> None:
    model = ScriptedModel(
        [
            ModelStep(
                output=[
                    function_call(
                        "get_customer",
                        {"customer_id": "C000"},
                        call_id="call-boom",
                    )
                ]
            ),
            ModelStep(
                output=[assistant_message("saw the error", item_id="msg-boom")]
            ),
        ]
    )
    record = run_task(
        booking_task(),
        runs_dir=tmp_path,
        model=model,
        policy=_BoomPolicy(),
    )
    assert record.error is None
    timeline, _ = _timeline(record)
    types = [event["event_type"] for event in timeline]
    assert types[-1] == "run_completed"
    failed = [
        event for event in timeline if event["event_type"] == "tool_failed"
    ]
    assert len(failed) == 1
    assert failed[0]["source"] == "facade"
    assert failed[0]["result"]["code"] == "facade_error"
    assert "injected boom" in failed[0]["result"]["error"]
    assert "final_output_proposed" in types


def test_keyboard_interrupt_finishes_trace_then_reraises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(coro, *_args, **_kwargs):
        coro.close()
        raise KeyboardInterrupt()

    monkeypatch.setattr("loopmedic.runner.run.asyncio.run", boom)
    with pytest.raises(KeyboardInterrupt):
        run_task(booking_task(), runs_dir=tmp_path)
    traces = list(tmp_path.glob("*.trace.db"))
    assert len(traces) == 1
    db = sqlite3.connect(traces[0])
    try:
        row = db.execute("SELECT status, error FROM runs").fetchone()
    finally:
        db.close()
    assert row is not None
    assert row[0] == "failed"
    assert "KeyboardInterrupt" in (row[1] or "")
