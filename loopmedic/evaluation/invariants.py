from __future__ import annotations

import sqlite3
from collections.abc import Callable

from pydantic import BaseModel

from loopmedic.evaluation.tasks import TaskSpec

InvariantFn = Callable[[sqlite3.Connection, TaskSpec], bool]


def _count(row: sqlite3.Row | tuple[object, ...] | None) -> int:
    if row is None:
        return 0
    if isinstance(row, sqlite3.Row):
        return int(row["n"] if "n" in row.keys() else row[0])
    return int(row[0])


class EvaluationResult(BaseModel):
    passed: bool
    checks: dict[str, bool]


def exactly_one_active_appointment(
    conn: sqlite3.Connection,
    task: TaskSpec,
) -> bool:
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM appointments
        WHERE customer_id = ? AND status = 'CONFIRMED'
        """,
        (task.customer_id,),
    ).fetchone()
    return _count(row) == 1


def new_appointment_matches_request(
    conn: sqlite3.Connection,
    task: TaskSpec,
) -> bool:
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM appointments
        WHERE customer_id = ?
          AND status = 'CONFIRMED'
          AND day = ?
          AND period = ?
        """,
        (task.customer_id, task.requested_day, task.requested_period),
    ).fetchone()
    return _count(row) == 1


def old_appointment_cancelled(
    conn: sqlite3.Connection,
    task: TaskSpec,
) -> bool:
    if task.original_appointment_id is None:
        return False
    row = conn.execute(
        "SELECT status FROM appointments WHERE appointment_id = ?",
        (task.original_appointment_id,),
    ).fetchone()
    if row is None:
        return False
    status = row[0] if not isinstance(row, sqlite3.Row) else row["status"]
    return status == "CANCELLED"


def confirmation_sent(conn: sqlite3.Connection, task: TaskSpec) -> bool:
    row = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM notifications AS n
        JOIN appointments AS a
          ON a.appointment_id = n.appointment_id
        WHERE a.customer_id = ?
          AND a.status = 'CONFIRMED'
          AND n.type = 'confirmation'
        """,
        (task.customer_id,),
    ).fetchone()
    return _count(row) >= 1


def no_duplicate_booking_final(
    conn: sqlite3.Connection,
    task: TaskSpec,
) -> bool:
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM appointments
        WHERE customer_id = ? AND status = 'CONFIRMED'
        """,
        (task.customer_id,),
    ).fetchone()
    return _count(row) <= 1


INVARIANTS: dict[str, InvariantFn] = {
    "exactly_one_active_appointment": exactly_one_active_appointment,
    "new_appointment_matches_request": new_appointment_matches_request,
    "old_appointment_cancelled": old_appointment_cancelled,
    "confirmation_sent": confirmation_sent,
    "no_duplicate_booking_final": no_duplicate_booking_final,
}


def evaluate(conn: sqlite3.Connection, task: TaskSpec) -> EvaluationResult:
    checks: dict[str, bool] = {}
    for name in task.required_invariants:
        fn = INVARIANTS.get(name)
        if fn is None:
            raise KeyError(f"unknown invariant {name}")
        checks[name] = fn(conn, task)
    return EvaluationResult(passed=all(checks.values()), checks=checks)
