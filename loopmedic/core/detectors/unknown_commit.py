from __future__ import annotations

import sqlite3
from typing import Any

from loopmedic.core.detectors.base import DetectorHit
from loopmedic.core.events import TraceEvent
from loopmedic.core.features import FeatureState
from loopmedic.environment.service import LEDGER_SUCCEEDED, operation_fingerprint
from loopmedic.facade.faults import TIMEOUT_CODE, WRITE_ENTITY, WRITE_TOOLS

NAME = "unknown_commit"


def write_fingerprint(
    run_id: str,
    tool: str | None,
    arguments: Any,
) -> str | None:
    keys = WRITE_ENTITY.get(tool or "")
    if not keys or not isinstance(arguments, dict):
        return None
    try:
        parts = tuple(str(arguments[name]) for name in keys)
    except KeyError:
        return None
    return operation_fingerprint(run_id, tool or "", *parts)


def ledger_succeeded(conn: sqlite3.Connection, fingerprint: str) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM operation_ledger
        WHERE fingerprint = ? AND status = ?
        LIMIT 1
        """,
        (fingerprint, LEDGER_SUCCEEDED),
    ).fetchone()
    return row is not None


def is_timeout(event: TraceEvent) -> bool:
    result = event.result if isinstance(event.result, dict) else {}
    return result.get("code") == TIMEOUT_CODE


def check(
    event: TraceEvent,
    features: FeatureState,
    *,
    conn: sqlite3.Connection,
    **_: Any,
) -> DetectorHit | None:
    del features
    tool = event.tool_name
    if tool not in WRITE_TOOLS:
        return None
    fingerprint = write_fingerprint(event.run_id, tool, event.arguments)
    if fingerprint is None:
        return None
    if not ledger_succeeded(conn, fingerprint):
        return None
    if event.event_type == "tool_failed" and is_timeout(event):
        return DetectorHit(
            detector=NAME,
            evidence={
                "trigger": "proactive",
                "tool": tool,
                "fingerprint": fingerprint,
                "ledger_status": LEDGER_SUCCEEDED,
                "state_hash_before": event.state_hash_before,
                "state_hash_after": event.state_hash_after,
            },
        )
    if event.event_type == "tool_proposed":
        return DetectorHit(
            detector=NAME,
            evidence={
                "trigger": "reactive",
                "tool": tool,
                "fingerprint": fingerprint,
                "ledger_status": LEDGER_SUCCEEDED,
            },
        )
    return None
