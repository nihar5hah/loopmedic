from __future__ import annotations

import argparse
import random
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
DEFAULT_DB_PATH = Path(__file__).with_name("pristine.db")
DEFAULT_SEED = 42

_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
_PERIODS = ("morning", "afternoon")
_NAMES = ("Asha Patel", "Ben Okonkwo", "Clara Nguyen")
_TIMEZONES = ("America/New_York", "America/Chicago", "America/Los_Angeles")
_PLANS = ("standard", "standard", "priority")


def write_pristine_db(path: Path, seed: int = DEFAULT_SEED) -> None:
    rng = random.Random(seed)
    names = list(_NAMES)
    rng.shuffle(names)

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA page_size = 4096")
        conn.execute("PRAGMA encoding = 'UTF-8'")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.execute("PRAGMA user_version = 1")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

        customers = [
            (f"C{i:03d}", names[i], _TIMEZONES[i], _PLANS[i])
            for i in range(len(names))
        ]
        conn.executemany(
            "INSERT INTO customers VALUES (?, ?, ?, ?)",
            customers,
        )

        slots = [
            (
                f"S{n:03d}",
                "appliance",
                day,
                period,
                2,
            )
            for n, (day, period) in enumerate(
                ((d, p) for d in _DAYS for p in _PERIODS),
                start=1,
            )
        ]
        conn.executemany(
            "INSERT INTO slots VALUES (?, ?, ?, ?, ?)",
            slots,
        )

        tuesday_morning = next(
            slot_id
            for slot_id, _, day, period, _ in slots
            if day == "Tuesday" and period == "morning"
        )
        conn.execute(
            """
            INSERT INTO appointments VALUES (
              'A001', 'C001', ?, 'appliance', 'Tuesday', 'morning',
              'CONFIRMED', 1, 0, NULL
            )
            """,
            (tuesday_morning,),
        )
        conn.execute("INSERT INTO world_meta (id, step) VALUES (1, 0)")
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a seeded pristine appointment DB.")
    parser.add_argument("--out", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    write_pristine_db(args.out, args.seed)


if __name__ == "__main__":
    main()
