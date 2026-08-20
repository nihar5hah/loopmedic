from __future__ import annotations

import hashlib
import sqlite3
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

HOLD_TTL_STEPS = 30
LEDGER_SUCCEEDED = "SUCCEEDED"
BOOKING_POLICY = (
    "Appliance-service booking policy.\n"
    "- Hold a slot, then create a confirmed appointment with that hold.\n"
    "- Holds expire after 30 logical steps and are not appointments.\n"
    "- Creating an appointment does not consume the hold.\n"
    "- Reschedule by creating the replacement before cancelling the original.\n"
    "- Cancellation is allowed. Confirmations require an existing appointment."
)

T = TypeVar("T")


class DomainError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def operation_fingerprint(run_id: str, tool: str, *entity_parts: str) -> str:
    """Stable write identity: hash(run_id, tool, target entity).

    For create_appointment the entity is customer+slot, not hold_id, so a
    retry that drops or replaces the hold still matches. The facade must
    pass the same run_id used here when it computes fingerprints.
    """
    material = "\x1f".join((run_id, tool, *entity_parts))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def new_attempt_id() -> str:
    return uuid.uuid4().hex


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def current_step(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT step FROM world_meta WHERE id = 1").fetchone()
    if row is None:
        raise DomainError("no_clock", "world_meta is missing")
    return int(row["step"])


def hold_is_active(hold: sqlite3.Row, step: int) -> bool:
    if int(hold["released"]) == 1:
        return False
    return step < int(hold["created_step"]) + int(hold["ttl_steps"])


def get_customer(conn: sqlite3.Connection, customer_id: str) -> dict[str, Any]:
    return _run(conn, True, lambda step: _get_customer(conn, customer_id, step))


def list_customer_appointments(
    conn: sqlite3.Connection,
    customer_id: str,
) -> dict[str, Any]:
    return _run(
        conn,
        True,
        lambda step: _list_customer_appointments(conn, customer_id, step),
    )


def search_available_slots(
    conn: sqlite3.Connection,
    day: str | None = None,
    period: str | None = None,
    service_type: str = "appliance",
) -> dict[str, Any]:
    return _run(
        conn,
        True,
        lambda step: _search_available_slots(
            conn, day, period, service_type, step
        ),
    )


def get_appointment(
    conn: sqlite3.Connection,
    appointment_id: str,
) -> dict[str, Any]:
    return _run(
        conn,
        True,
        lambda step: _get_appointment(conn, appointment_id, step),
    )


def get_booking_policy(conn: sqlite3.Connection) -> dict[str, Any]:
    return _run(conn, True, lambda step: {"policy": BOOKING_POLICY, "step": step})


def hold_slot(
    conn: sqlite3.Connection,
    customer_id: str,
    slot_id: str,
    attempt_id: str,
    fingerprint: str,
    ttl_steps: int = HOLD_TTL_STEPS,
    *,
    autocommit: bool = True,
) -> dict[str, Any]:
    return _run(
        conn,
        autocommit,
        lambda step: _hold_slot(
            conn,
            customer_id,
            slot_id,
            attempt_id,
            fingerprint,
            ttl_steps,
            step,
        ),
    )


def release_hold(
    conn: sqlite3.Connection,
    hold_id: str,
    attempt_id: str,
    fingerprint: str,
    *,
    autocommit: bool = True,
) -> dict[str, Any]:
    return _run(
        conn,
        autocommit,
        lambda step: _release_hold(conn, hold_id, attempt_id, fingerprint, step),
    )


def create_appointment(
    conn: sqlite3.Connection,
    customer_id: str,
    slot_id: str,
    hold_id: str,
    attempt_id: str,
    fingerprint: str,
    *,
    autocommit: bool = True,
) -> dict[str, Any]:
    return _run(
        conn,
        autocommit,
        lambda step: _create_appointment(
            conn,
            customer_id,
            slot_id,
            hold_id,
            attempt_id,
            fingerprint,
            step,
        ),
    )


def cancel_appointment(
    conn: sqlite3.Connection,
    appointment_id: str,
    attempt_id: str,
    fingerprint: str,
    expected_version: int | None = None,
    *,
    autocommit: bool = True,
) -> dict[str, Any]:
    return _run(
        conn,
        autocommit,
        lambda step: _cancel_appointment(
            conn,
            appointment_id,
            attempt_id,
            fingerprint,
            expected_version,
            step,
        ),
    )


def send_confirmation(
    conn: sqlite3.Connection,
    appointment_id: str,
    attempt_id: str,
    fingerprint: str,
    *,
    autocommit: bool = True,
) -> dict[str, Any]:
    return _run(
        conn,
        autocommit,
        lambda step: _send_confirmation(
            conn, appointment_id, attempt_id, fingerprint, step
        ),
    )


def _run(
    conn: sqlite3.Connection,
    autocommit: bool,
    body: Callable[[int], T],
) -> T:
    if not conn.in_transaction:
        conn.execute("BEGIN")
    step = _advance_step(conn)
    try:
        result = body(step)
    except DomainError:
        if autocommit:
            conn.commit()
        raise
    except Exception:
        conn.rollback()
        raise
    if autocommit:
        conn.commit()
    return result


def _advance_step(conn: sqlite3.Connection) -> int:
    new_step = current_step(conn) + 1
    conn.execute("UPDATE world_meta SET step = ? WHERE id = 1", (new_step,))
    return new_step


def _as_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _require_customer(conn: sqlite3.Connection, customer_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM customers WHERE customer_id = ?",
        (customer_id,),
    ).fetchone()
    if row is None:
        raise DomainError("not_found", f"unknown customer {customer_id}")
    return row


def _require_slot(conn: sqlite3.Connection, slot_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM slots WHERE slot_id = ?",
        (slot_id,),
    ).fetchone()
    if row is None:
        raise DomainError("not_found", f"unknown slot {slot_id}")
    return row


def _require_appointment(
    conn: sqlite3.Connection,
    appointment_id: str,
) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM appointments WHERE appointment_id = ?",
        (appointment_id,),
    ).fetchone()
    if row is None:
        raise DomainError(
            "not_found",
            f"unknown appointment {appointment_id}",
        )
    return row


def _confirmed_on_slot(conn: sqlite3.Connection, slot_id: str) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM appointments
        WHERE slot_id = ? AND status = 'CONFIRMED'
        """,
        (slot_id,),
    ).fetchone()
    return int(row["n"])


def _insert_ledger(
    conn: sqlite3.Connection,
    attempt_id: str,
    fingerprint: str,
    tool: str,
    result_ref: str,
    step: int,
) -> None:
    conn.execute(
        """
        INSERT INTO operation_ledger
          (attempt_id, fingerprint, tool, status, result_ref, step)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (attempt_id, fingerprint, tool, LEDGER_SUCCEEDED, result_ref, step),
    )


def _get_customer(
    conn: sqlite3.Connection,
    customer_id: str,
    step: int,
) -> dict[str, Any]:
    row = _require_customer(conn, customer_id)
    result = _as_dict(row)
    result["step"] = step
    return result


def _list_customer_appointments(
    conn: sqlite3.Connection,
    customer_id: str,
    step: int,
) -> dict[str, Any]:
    _require_customer(conn, customer_id)
    rows = conn.execute(
        """
        SELECT * FROM appointments
        WHERE customer_id = ?
        ORDER BY appointment_id
        """,
        (customer_id,),
    ).fetchall()
    return {"appointments": [_as_dict(row) for row in rows], "step": step}


def _search_available_slots(
    conn: sqlite3.Connection,
    day: str | None,
    period: str | None,
    service_type: str,
    step: int,
) -> dict[str, Any]:
    # Remaining capacity counts CONFIRMED appointments only. Active holds
    # do not reserve a seat; otherwise a retry after post-commit loss
    # could fail on capacity and Demo 2 would be fake.
    rows = conn.execute(
        """
        SELECT
          s.slot_id,
          s.service_type,
          s.day,
          s.period,
          s.capacity,
          s.capacity - IFNULL(booked.n, 0) AS remaining
        FROM slots AS s
        LEFT JOIN (
          SELECT slot_id, COUNT(*) AS n
          FROM appointments
          WHERE status = 'CONFIRMED'
          GROUP BY slot_id
        ) AS booked ON booked.slot_id = s.slot_id
        WHERE s.service_type = ?
          AND (? IS NULL OR s.day = ?)
          AND (? IS NULL OR s.period = ?)
          AND s.capacity - IFNULL(booked.n, 0) > 0
        ORDER BY s.slot_id
        """,
        (service_type, day, day, period, period),
    ).fetchall()
    return {"slots": [_as_dict(row) for row in rows], "step": step}


def _get_appointment(
    conn: sqlite3.Connection,
    appointment_id: str,
    step: int,
) -> dict[str, Any]:
    row = _require_appointment(conn, appointment_id)
    result = _as_dict(row)
    result["step"] = step
    return result


def _hold_slot(
    conn: sqlite3.Connection,
    customer_id: str,
    slot_id: str,
    attempt_id: str,
    fingerprint: str,
    ttl_steps: int,
    step: int,
) -> dict[str, Any]:
    _require_customer(conn, customer_id)
    _require_slot(conn, slot_id)
    if ttl_steps < 1:
        raise DomainError("invalid_ttl", "ttl_steps must be >= 1")
    hold_id = f"H{step:03d}"
    conn.execute(
        """
        INSERT INTO holds (
          hold_id, slot_id, customer_id, created_step, ttl_steps, released
        ) VALUES (?, ?, ?, ?, ?, 0)
        """,
        (hold_id, slot_id, customer_id, step, ttl_steps),
    )
    _insert_ledger(conn, attempt_id, fingerprint, "hold_slot", hold_id, step)
    return {
        "hold_id": hold_id,
        "slot_id": slot_id,
        "customer_id": customer_id,
        "created_step": step,
        "ttl_steps": ttl_steps,
        "released": 0,
        "step": step,
    }


def _release_hold(
    conn: sqlite3.Connection,
    hold_id: str,
    attempt_id: str,
    fingerprint: str,
    step: int,
) -> dict[str, Any]:
    hold = conn.execute(
        "SELECT * FROM holds WHERE hold_id = ?",
        (hold_id,),
    ).fetchone()
    if hold is None:
        raise DomainError("not_found", f"unknown hold {hold_id}")
    if int(hold["released"]) == 1:
        raise DomainError("hold_released", f"hold {hold_id} already released")
    conn.execute(
        "UPDATE holds SET released = 1 WHERE hold_id = ?",
        (hold_id,),
    )
    _insert_ledger(conn, attempt_id, fingerprint, "release_hold", hold_id, step)
    return {"hold_id": hold_id, "released": 1, "step": step}


def _create_appointment(
    conn: sqlite3.Connection,
    customer_id: str,
    slot_id: str,
    hold_id: str,
    attempt_id: str,
    fingerprint: str,
    step: int,
) -> dict[str, Any]:
    _require_customer(conn, customer_id)
    slot = _require_slot(conn, slot_id)
    hold = conn.execute(
        "SELECT * FROM holds WHERE hold_id = ?",
        (hold_id,),
    ).fetchone()
    if hold is None:
        raise DomainError("not_found", f"unknown hold {hold_id}")
    if hold["customer_id"] != customer_id or hold["slot_id"] != slot_id:
        raise DomainError(
            "hold_mismatch",
            "hold does not match customer and slot",
        )
    if not hold_is_active(hold, step):
        raise DomainError("hold_inactive", f"hold {hold_id} is not active")
    if _confirmed_on_slot(conn, slot_id) >= int(slot["capacity"]):
        raise DomainError("slot_full", f"slot {slot_id} is at capacity")
    appointment_id = f"A{step:03d}"
    conn.execute(
        """
        INSERT INTO appointments (
          appointment_id, customer_id, slot_id, service_type, day, period,
          status, version, created_step, cancelled_step
        ) VALUES (?, ?, ?, ?, ?, ?, 'CONFIRMED', 1, ?, NULL)
        """,
        (
            appointment_id,
            customer_id,
            slot_id,
            slot["service_type"],
            slot["day"],
            slot["period"],
            step,
        ),
    )
    _insert_ledger(
        conn,
        attempt_id,
        fingerprint,
        "create_appointment",
        appointment_id,
        step,
    )
    return {
        "appointment_id": appointment_id,
        "customer_id": customer_id,
        "slot_id": slot_id,
        "status": "CONFIRMED",
        "version": 1,
        "hold_id": hold_id,
        "step": step,
    }


def _cancel_appointment(
    conn: sqlite3.Connection,
    appointment_id: str,
    attempt_id: str,
    fingerprint: str,
    expected_version: int | None,
    step: int,
) -> dict[str, Any]:
    appt = _require_appointment(conn, appointment_id)
    if appt["status"] != "CONFIRMED":
        raise DomainError(
            "not_confirmed",
            f"appointment {appointment_id} is {appt['status']}",
        )
    if (
        expected_version is not None
        and int(appt["version"]) != expected_version
    ):
        raise DomainError(
            "version_mismatch",
            f"expected version {expected_version}, found {appt['version']}",
        )
    new_version = int(appt["version"]) + 1
    conn.execute(
        """
        UPDATE appointments
        SET status = 'CANCELLED', cancelled_step = ?, version = ?
        WHERE appointment_id = ?
        """,
        (step, new_version, appointment_id),
    )
    _insert_ledger(
        conn,
        attempt_id,
        fingerprint,
        "cancel_appointment",
        appointment_id,
        step,
    )
    return {
        "appointment_id": appointment_id,
        "status": "CANCELLED",
        "version": new_version,
        "step": step,
    }


def _send_confirmation(
    conn: sqlite3.Connection,
    appointment_id: str,
    attempt_id: str,
    fingerprint: str,
    step: int,
) -> dict[str, Any]:
    appt = _require_appointment(conn, appointment_id)
    notification_id = f"N{step:03d}"
    conn.execute(
        """
        INSERT INTO notifications (
          notification_id, customer_id, appointment_id, type
        ) VALUES (?, ?, ?, 'confirmation')
        """,
        (notification_id, appt["customer_id"], appointment_id),
    )
    _insert_ledger(
        conn,
        attempt_id,
        fingerprint,
        "send_confirmation",
        notification_id,
        step,
    )
    return {
        "notification_id": notification_id,
        "appointment_id": appointment_id,
        "customer_id": appt["customer_id"],
        "type": "confirmation",
        "step": step,
    }
