from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from loopmedic.environment.seed import SCHEMA_PATH, write_pristine_db

SCHEMA_TABLES = {
    "customers",
    "slots",
    "appointments",
    "holds",
    "notifications",
    "operation_ledger",
    "world_meta",
}


def test_schema_creates_expected_tables() -> None:
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    names = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    assert names == SCHEMA_TABLES


def test_schema_rejects_capacity_below_two() -> None:
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO slots VALUES ('S999', 'appliance', 'Monday', 'morning', 1)
            """
        )


def test_seed_is_byte_identical(tmp_path: Path) -> None:
    a = tmp_path / "a.db"
    b = tmp_path / "b.db"
    write_pristine_db(a, seed=42)
    write_pristine_db(b, seed=42)
    assert a.read_bytes() == b.read_bytes()
