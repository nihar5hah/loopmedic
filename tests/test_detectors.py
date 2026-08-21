from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from loopmedic.core.detectors import (
    attach_detectors,
    budget,
    error_streak,
    premature,
    repetition,
    stagnation,
    unknown_commit,
)
from loopmedic.core.detectors.base import DetectorHit
from loopmedic.core.events import TraceEvent
from loopmedic.core.features import FeatureState, normalize_error
from loopmedic.core.trace_store import TraceStore
from loopmedic.environment.seed import write_pristine_db
from loopmedic.environment.service import (
    connect,
    create_appointment,
    hold_slot,
    new_attempt_id,
    operation_fingerprint,
    send_confirmation,
)
from loopmedic.evaluation.invariants import evaluate
from loopmedic.evaluation.scenario import load_scenario
from loopmedic.evaluation.tasks import booking_task
from loopmedic.facade.faults import timeout_payload
from loopmedic.runner.config import PROJECT_ROOT, TOOL_CALL_CAP
from loopmedic.runner.run import run_task

SCENARIOS = PROJECT_ROOT / "scenarios"


def _event(event_type: str, **fields: Any) -> TraceEvent:
    payload: dict[str, Any] = {
        "run_id": "det",
        "event_id": uuid.uuid4().hex,
        "step_index": 0,
        "source": "harness",
        "event_type": event_type,
    }
    payload.update(fields)
    return TraceEvent(**payload)


def _run(
    check,
    events: list[TraceEvent],
    *,
    cap: int = TOOL_CALL_CAP,
    conn=None,
    task=None,
) -> list[DetectorHit]:
    state = FeatureState(cap=cap)
    hits: list[DetectorHit] = []
    for event in events:
        state.observe(event)
        hit = check(event, state, conn=conn, task=task)
        if hit is not None:
            hits.append(hit)
    return hits


def _world(tmp_path: Path):
    db_path = tmp_path / "world.db"
    write_pristine_db(db_path, seed=42)
    return connect(db_path)


def _book_c000(conn, run_id: str) -> str:
    hold = hold_slot(
        conn,
        "C000",
        "S001",
        new_attempt_id(),
        operation_fingerprint(run_id, "hold_slot", "C000", "S001"),
    )
    created = create_appointment(
        conn,
        "C000",
        "S001",
        hold["hold_id"],
        new_attempt_id(),
        operation_fingerprint(run_id, "create_appointment", "C000", "S001"),
    )
    send_confirmation(
        conn,
        created["appointment_id"],
        new_attempt_id(),
        operation_fingerprint(
            run_id,
            "send_confirmation",
            created["appointment_id"],
        ),
    )
    return str(created["appointment_id"])


def test_repetition_fires_on_second_identical_signature() -> None:
    args = {"customer_id": "C000"}
    events = [
        _event("tool_proposed", tool_name="get_customer", arguments=args),
        _event("tool_proposed", tool_name="get_customer", arguments=args),
    ]
    hits = _run(repetition.check, events)
    assert len(hits) == 1
    assert hits[0].detector == "repetition"
    assert hits[0].evidence["streak"] == 2
    assert hits[0].evidence["tool"] == "get_customer"


def test_repetition_does_not_fire_on_single_or_changed_args() -> None:
    first = _event(
        "tool_proposed",
        tool_name="get_customer",
        arguments={"customer_id": "C000"},
    )
    assert _run(repetition.check, [first]) == []
    changed = [
        first,
        _event(
            "tool_proposed",
            tool_name="get_customer",
            arguments={"customer_id": "C001"},
        ),
    ]
    assert _run(repetition.check, changed) == []


def test_error_streak_fires_on_second_unchanged_failure() -> None:
    payload = {
        "ok": False,
        "code": "transient_error",
        "error": "transient error",
    }
    args = {"customer_id": "C000", "slot_id": "S001"}
    failed = [
        _event(
            "tool_failed",
            tool_name="hold_slot",
            arguments=args,
            result=payload,
            error="transient error",
            state_hash_before="h0",
            state_hash_after="h0",
        )
        for _ in range(2)
    ]
    hits = _run(error_streak.check, failed)
    assert len(hits) == 1
    assert hits[0].evidence["streak"] == 2
    assert hits[0].evidence["normalized_error"] == "transient_error:transient error"


def test_error_streak_does_not_fire_when_hash_changes() -> None:
    payload = timeout_payload()
    args = {"customer_id": "C000", "slot_id": "S001", "hold_id": "H001"}
    events = [
        _event(
            "tool_failed",
            tool_name="create_appointment",
            arguments=args,
            result=payload,
            error=payload["error"],
            state_hash_before="before",
            state_hash_after="after",
        ),
        _event(
            "tool_failed",
            tool_name="create_appointment",
            arguments=args,
            result=payload,
            error=payload["error"],
            state_hash_before="after",
            state_hash_after="after2",
        ),
    ]
    assert _run(error_streak.check, events) == []


def test_error_streak_normalizes_volatile_ids() -> None:
    args = {"appointment_id": "A001"}
    events = [
        _event(
            "tool_failed",
            tool_name="get_appointment",
            arguments=args,
            result={
                "ok": False,
                "code": "not_found",
                "error": "missing abcdef012345",
            },
            error="missing abcdef012345",
            state_hash_before="h",
            state_hash_after="h",
        ),
        _event(
            "tool_failed",
            tool_name="get_appointment",
            arguments=args,
            result={
                "ok": False,
                "code": "not_found",
                "error": "missing fedcba543210",
            },
            error="missing fedcba543210",
            state_hash_before="h",
            state_hash_after="h",
        ),
    ]
    assert normalize_error(events[0]) == normalize_error(events[1])
    hits = _run(error_streak.check, events)
    assert len(hits) == 1


def test_stagnation_fires_after_five_unchanged_steps() -> None:
    digest = "same-hash"
    terminals = [
        _event(
            "tool_completed",
            tool_name="get_customer",
            arguments={"customer_id": "C000"},
            state_hash_before=digest,
            state_hash_after=digest,
        )
        for _ in range(5)
    ]
    events = [_event("run_started", state_hash_after=digest), *terminals]
    hits = _run(stagnation.check, events)
    assert [hit.evidence["steps_unchanged"] for hit in hits] == [5]


def test_stagnation_does_not_fire_on_four_opening_reads() -> None:
    digest = "same-hash"
    terminals = [
        _event(
            "tool_completed",
            tool_name="get_customer",
            arguments={"customer_id": "C000"},
            state_hash_before=digest,
            state_hash_after=digest,
        )
        for _ in range(4)
    ]
    events = [_event("run_started", state_hash_after=digest), *terminals]
    assert _run(stagnation.check, events) == []


def test_budget_fires_at_80_percent_of_cap() -> None:
    events = [
        _event(
            "tool_proposed",
            tool_name="get_customer",
            arguments={"customer_id": f"C{i:03d}"},
        )
        for i in range(4)
    ]
    assert _run(budget.check, events[:3], cap=5) == []
    hits = _run(budget.check, events, cap=5)
    assert len(hits) == 1
    assert hits[0].evidence["tool_calls"] == 4
    assert hits[0].evidence["fraction"] == 0.8


def test_unknown_commit_proactive_on_timeout_after_succeeded(
    tmp_path: Path,
) -> None:
    conn = _world(tmp_path)
    try:
        _book_c000(conn, "det")
        timeout = _event(
            "tool_failed",
            tool_name="create_appointment",
            arguments={
                "customer_id": "C000",
                "slot_id": "S001",
                "hold_id": "H001",
            },
            result=timeout_payload(),
            error=timeout_payload()["error"],
            state_hash_before="before",
            state_hash_after="after",
            injected_fault="post_commit_response_loss",
        )
        hits = _run(unknown_commit.check, [timeout], conn=conn)
        assert len(hits) == 1
        assert hits[0].evidence["trigger"] == "proactive"
        assert "injected_fault" not in hits[0].evidence
        assert hits[0].evidence["ledger_status"] == "SUCCEEDED"
    finally:
        conn.close()


def test_unknown_commit_reactive_on_matching_propose(tmp_path: Path) -> None:
    conn = _world(tmp_path)
    try:
        _book_c000(conn, "det")
        proposed = _event(
            "tool_proposed",
            tool_name="create_appointment",
            arguments={
                "customer_id": "C000",
                "slot_id": "S001",
                "hold_id": "H999",
            },
        )
        hits = _run(unknown_commit.check, [proposed], conn=conn)
        assert len(hits) == 1
        assert hits[0].evidence["trigger"] == "reactive"
        assert "injected_fault" not in hits[0].evidence
    finally:
        conn.close()


def test_unknown_commit_does_not_fire_without_ledger_or_on_read(
    tmp_path: Path,
) -> None:
    conn = _world(tmp_path)
    try:
        timeout = _event(
            "tool_failed",
            tool_name="create_appointment",
            arguments={
                "customer_id": "C000",
                "slot_id": "S001",
                "hold_id": "H001",
            },
            result=timeout_payload(),
            error=timeout_payload()["error"],
            state_hash_before="h",
            state_hash_after="h",
        )
        assert _run(unknown_commit.check, [timeout], conn=conn) == []
        read_timeout = _event(
            "tool_failed",
            tool_name="get_customer",
            arguments={"customer_id": "C000"},
            result=timeout_payload(),
            error=timeout_payload()["error"],
        )
        assert _run(unknown_commit.check, [read_timeout], conn=conn) == []
    finally:
        conn.close()


def test_premature_completion_fires_when_invariants_fail(tmp_path: Path) -> None:
    conn = _world(tmp_path)
    task = booking_task()
    try:
        event = _event(
            "final_output_proposed",
            result="done without booking",
        )
        hits = _run(premature.check, [event], conn=conn, task=task)
        assert len(hits) == 1
        assert hits[0].detector == "premature_completion"
        assert hits[0].evidence["checks"]["confirmation_sent"] is False
    finally:
        conn.close()


def test_premature_completion_does_not_fire_when_invariants_pass(
    tmp_path: Path,
) -> None:
    conn = _world(tmp_path)
    task = booking_task()
    try:
        _book_c000(conn, "det")
        assert evaluate(conn, task).passed is True
        event = _event("final_output_proposed", result="booked")
        assert _run(premature.check, [event], conn=conn, task=task) == []
    finally:
        conn.close()


def test_attach_persists_repetition_fire(tmp_path: Path) -> None:
    conn = _world(tmp_path)
    store = TraceStore(tmp_path / "trace.db")
    try:
        attach_detectors(store, conn, cap=15)
        store.start_run("det")
        args = {"customer_id": "C000"}
        store.emit(
            "det",
            "tool_proposed",
            step_index=0,
            tool_name="get_customer",
            arguments=args,
        )
        store.emit(
            "det",
            "tool_proposed",
            step_index=0,
            tool_name="get_customer",
            arguments=args,
        )
        hits = store.list_detector_outputs("det")
        assert [row["detector"] for row in hits] == ["repetition"]
        assert hits[0]["fired"] is True
        assert hits[0]["evidence"]["streak"] == 2
    finally:
        store.close()
        conn.close()


def test_listener_exception_does_not_fail_emit(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "trace.db")
    seen: list[str] = []
    try:
        store.start_run("det")

        def boom(_event) -> None:
            raise RuntimeError("listener boom")

        def track(event) -> None:
            seen.append(event.event_type)

        store.add_listener(boom)
        store.add_listener(track)
        event = store.emit("det", "llm_started", step_index=0)
        assert event.event_type == "llm_started"
        assert [row.event_type for row in store.list_events("det")] == [
            "llm_started"
        ]
        assert seen == ["llm_started"]
    finally:
        store.close()


def test_one_detector_exception_does_not_drop_others(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from loopmedic.core import detectors as det_mod

    def boom(*_args, **_kwargs):
        raise RuntimeError("detector boom")

    monkeypatch.setattr(
        det_mod,
        "DETECTORS",
        (("boom", boom), (repetition.NAME, repetition.check)),
    )
    conn = _world(tmp_path)
    store = TraceStore(tmp_path / "trace.db")
    try:
        attach_detectors(store, conn, cap=15)
        store.start_run("det")
        args = {"customer_id": "C000"}
        store.emit(
            "det",
            "tool_proposed",
            step_index=0,
            tool_name="get_customer",
            arguments=args,
        )
        store.emit(
            "det",
            "tool_proposed",
            step_index=0,
            tool_name="get_customer",
            arguments=args,
        )
        hits = store.list_detector_outputs("det")
        assert [row["detector"] for row in hits] == ["repetition"]
    finally:
        store.close()
        conn.close()


def test_record_detector_failure_is_logged_and_does_not_fail_emit(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    import logging
    import sqlite3

    conn = _world(tmp_path)
    store = TraceStore(tmp_path / "trace.db")
    try:
        attach_detectors(store, conn, cap=15)
        store.start_run("det")

        def fail_record(*_args, **_kwargs):
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr(store, "record_detector", fail_record)
        caplog.set_level(logging.WARNING, logger="loopmedic.core.detectors")
        args = {"customer_id": "C000"}
        store.emit(
            "det",
            "tool_proposed",
            step_index=0,
            tool_name="get_customer",
            arguments=args,
        )
        second = store.emit(
            "det",
            "tool_proposed",
            step_index=0,
            tool_name="get_customer",
            arguments=args,
        )
        assert [row.event_type for row in store.list_events("det")] == [
            "tool_proposed",
            "tool_proposed",
        ]
        assert store.list_detector_outputs("det") == []
        assert any(
            "failed to persist detector repetition" in record.getMessage()
            and second.event_id in record.getMessage()
            for record in caplog.records
        )
    finally:
        store.close()
        conn.close()


def test_scripted_post_commit_records_unknown_commit(tmp_path: Path) -> None:
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
    store = TraceStore(record.trace_path)
    try:
        hits = store.list_detector_outputs(record.run_id)
        unknown = [
            row for row in hits if row["detector"] == "unknown_commit"
        ]
        triggers = [row["evidence"]["trigger"] for row in unknown]
        assert "proactive" in triggers
        assert "reactive" in triggers
        for row in unknown:
            assert row["fired"] is True
            assert "injected_fault" not in row["evidence"]
        timeline = store.timeline(record.run_id)
        failed = next(
            event
            for event in timeline
            if event["event_type"] == "tool_failed"
            and event["tool_name"] == "create_appointment"
        )
        assert failed["injected_fault"] == "post_commit_response_loss"
        proactive = next(
            row
            for row in unknown
            if row["evidence"]["trigger"] == "proactive"
        )
        assert proactive["event_id"] == failed["event_id"]
    finally:
        store.close()
