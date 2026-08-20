from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from loopmedic.core.events import DomainSnapshot
from loopmedic.environment.service import current_step, hold_is_active

CUSTOMER_FIELDS = ("customer_id", "name", "timezone", "service_plan")
SLOT_FIELDS = ("slot_id", "service_type", "day", "period", "capacity")
APPOINTMENT_FIELDS = (
    "appointment_id",
    "customer_id",
    "slot_id",
    "service_type",
    "day",
    "period",
    "status",
    "version",
)
NOTIFICATION_FIELDS = (
    "notification_id",
    "customer_id",
    "appointment_id",
    "type",
)


def effective_hold_status(hold: sqlite3.Row, step: int) -> str:
    if int(hold["released"]) == 1:
        return "RELEASED"
    if hold_is_active(hold, step):
        return "ACTIVE"
    return "EXPIRED"


def snapshot_world(conn: sqlite3.Connection) -> DomainSnapshot:
    step = current_step(conn)
    return DomainSnapshot(
        customers=_rows(conn, "customers", "customer_id", CUSTOMER_FIELDS),
        slots=_rows(conn, "slots", "slot_id", SLOT_FIELDS),
        appointments=_rows(
            conn, "appointments", "appointment_id", APPOINTMENT_FIELDS
        ),
        holds=_hold_rows(conn, step),
        notifications=_rows(
            conn, "notifications", "notification_id", NOTIFICATION_FIELDS
        ),
    )


def canonical_json(snapshot: DomainSnapshot) -> str:
    return json.dumps(
        snapshot.model_dump(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def hash_snapshot(snapshot: DomainSnapshot) -> str:
    material = canonical_json(snapshot)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def hash_world(conn: sqlite3.Connection) -> str:
    return hash_snapshot(snapshot_world(conn))


def _rows(
    conn: sqlite3.Connection,
    table: str,
    order_key: str,
    fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    quoted = ", ".join(fields)
    rows = conn.execute(
        f"SELECT {quoted} FROM {table} ORDER BY {order_key}"
    ).fetchall()
    return [{field: row[field] for field in fields} for row in rows]


def _hold_rows(conn: sqlite3.Connection, step: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT hold_id, slot_id, customer_id, created_step, ttl_steps, released
        FROM holds
        ORDER BY hold_id
        """
    ).fetchall()
    return [
        {
            "hold_id": row["hold_id"],
            "slot_id": row["slot_id"],
            "customer_id": row["customer_id"],
            "status": effective_hold_status(row, step),
        }
        for row in rows
    ]
