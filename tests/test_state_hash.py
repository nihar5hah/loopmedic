from __future__ import annotations

from pathlib import Path

from loopmedic.core.state_hash import (
    canonical_json,
    hash_snapshot,
    hash_world,
    snapshot_world,
)
from loopmedic.environment.seed import write_pristine_db
from loopmedic.environment.service import (
    connect,
    get_booking_policy,
    get_customer,
    hold_slot,
    operation_fingerprint,
    release_hold,
)


def _db(tmp_path: Path, name: str = "world.db"):
    path = tmp_path / name
    write_pristine_db(path, seed=42)
    return connect(path)


def test_key_ordering_does_not_change_hash(tmp_path: Path) -> None:
    conn = _db(tmp_path)
    snapshot = snapshot_world(conn)
    rekeyed_customers = [
        {key: row[key] for key in reversed(list(row))}
        for row in snapshot.customers
    ]
    shuffled = snapshot.model_copy(
        update={"customers": rekeyed_customers},
    )
    assert hash_snapshot(snapshot) == hash_snapshot(shuffled)
    dumped = canonical_json(snapshot)
    assert dumped == canonical_json(shuffled)
    conn.close()


def test_ledger_churn_does_not_change_hash(tmp_path: Path) -> None:
    conn = _db(tmp_path)
    before = hash_world(conn)
    conn.execute(
        """
        INSERT INTO operation_ledger
          (attempt_id, fingerprint, tool, status, result_ref, step)
        VALUES ('att-noise', 'fp-noise', 'create_appointment', 'SUCCEEDED',
                'A999', 0)
        """
    )
    conn.commit()
    assert hash_world(conn) == before
    conn.close()


def test_advancing_step_past_hold_ttl_changes_hash(tmp_path: Path) -> None:
    conn = _db(tmp_path)
    hold_slot(
        conn,
        "C000",
        "S001",
        "att-hold",
        operation_fingerprint("hash-test", "hold_slot", "C000", "S001"),
        ttl_steps=2,
    )
    active = hash_world(conn)
    conn.execute("UPDATE world_meta SET step = 2 WHERE id = 1")
    conn.commit()
    assert hash_world(conn) == active
    conn.execute("UPDATE world_meta SET step = 3 WHERE id = 1")
    conn.commit()
    expired = hash_world(conn)
    assert expired != active
    snapshot = snapshot_world(conn)
    assert snapshot.holds[0]["status"] == "EXPIRED"
    conn.close()


def test_releasing_an_expired_hold_changes_hash(tmp_path: Path) -> None:
    conn = _db(tmp_path)
    held = hold_slot(
        conn,
        "C000",
        "S001",
        "att-hold",
        operation_fingerprint("hash-test", "hold_slot", "C000", "S001"),
        ttl_steps=2,
    )
    conn.execute("UPDATE world_meta SET step = 3 WHERE id = 1")
    conn.commit()
    expired = hash_world(conn)
    assert snapshot_world(conn).holds[0]["status"] == "EXPIRED"
    release_hold(
        conn,
        held["hold_id"],
        "att-release",
        operation_fingerprint("hash-test", "release_hold", held["hold_id"]),
    )
    released = hash_world(conn)
    assert released != expired
    assert snapshot_world(conn).holds[0]["status"] == "RELEASED"
    conn.close()


def test_identical_states_from_different_call_orders_hash_equal(
    tmp_path: Path,
) -> None:
    first = _db(tmp_path, "a.db")
    get_customer(first, "C001")
    get_booking_policy(first)
    hash_a = hash_world(first)
    first.close()

    second = _db(tmp_path, "b.db")
    get_booking_policy(second)
    get_customer(second, "C001")
    hash_b = hash_world(second)
    second.close()

    assert hash_a == hash_b
