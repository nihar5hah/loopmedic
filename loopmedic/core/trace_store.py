from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from loopmedic.core.events import DomainSnapshot, EventSource, EventType, TraceEvent
from loopmedic.evaluation.tasks import TaskSpec

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  task_json TEXT,
  model TEXT,
  status TEXT NOT NULL,
  passed INTEGER,
  error TEXT
);

CREATE TABLE IF NOT EXISTS trace_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs (run_id),
  event_id TEXT NOT NULL UNIQUE,
  step_index INTEGER NOT NULL,
  source TEXT NOT NULL,
  event_type TEXT NOT NULL,
  tool_name TEXT,
  arguments TEXT,
  result TEXT,
  error TEXT,
  state_hash_before TEXT,
  state_hash_after TEXT,
  tokens INTEGER,
  injected_fault TEXT
);

CREATE TABLE IF NOT EXISTS state_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs (run_id),
  event_id TEXT NOT NULL,
  state_hash TEXT NOT NULL,
  snapshot_json TEXT NOT NULL,
  world_step INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS detector_outputs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs (run_id),
  event_id TEXT,
  detector TEXT NOT NULL,
  fired INTEGER NOT NULL,
  evidence_json TEXT
);

CREATE TABLE IF NOT EXISTS interventions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs (run_id),
  event_id TEXT,
  action TEXT NOT NULL,
  detail_json TEXT
);
"""


class TraceStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def start_run(
        self,
        run_id: str,
        task: TaskSpec | None = None,
        model: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO runs (run_id, task_json, model, status)
            VALUES (?, ?, ?, 'running')
            """,
            (
                run_id,
                task.model_dump_json() if task is not None else None,
                model,
            ),
        )
        self.conn.commit()

    def finish_run(
        self,
        run_id: str,
        *,
        passed: bool | None,
        error: str | None = None,
    ) -> None:
        status = "passed" if passed else "failed"
        if passed is None:
            status = "finished"
        self.conn.execute(
            """
            UPDATE runs
            SET status = ?, passed = ?, error = ?
            WHERE run_id = ?
            """,
            (
                status,
                None if passed is None else int(passed),
                error,
                run_id,
            ),
        )
        self.conn.commit()

    def append(
        self,
        event: TraceEvent,
        snapshot: DomainSnapshot | None = None,
        snapshot_hash: str | None = None,
    ) -> TraceEvent:
        self.conn.execute(
            """
            INSERT INTO trace_events (
              run_id, event_id, step_index, source, event_type, tool_name,
              arguments, result, error, state_hash_before, state_hash_after,
              tokens, injected_fault
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.run_id,
                event.event_id,
                event.step_index,
                event.source,
                event.event_type,
                event.tool_name,
                _dump_json(event.arguments),
                _dump_json(event.result),
                event.error,
                event.state_hash_before,
                event.state_hash_after,
                event.tokens,
                event.injected_fault,
            ),
        )
        if snapshot is not None:
            digest = snapshot_hash or event.state_hash_after
            if digest is None:
                raise ValueError("snapshot requires a hash")
            self.conn.execute(
                """
                INSERT INTO state_snapshots (
                  run_id, event_id, state_hash, snapshot_json, world_step
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.run_id,
                    event.event_id,
                    digest,
                    snapshot.model_dump_json(),
                    event.step_index,
                ),
            )
        self.conn.commit()
        return event

    def emit(
        self,
        run_id: str,
        event_type: EventType,
        *,
        step_index: int,
        source: EventSource = "harness",
        snapshot: DomainSnapshot | None = None,
        snapshot_hash: str | None = None,
        **fields: Any,
    ) -> TraceEvent:
        event = TraceEvent(
            run_id=run_id,
            event_id=uuid.uuid4().hex,
            step_index=step_index,
            source=source,
            event_type=event_type,
            **fields,
        )
        return self.append(event, snapshot=snapshot, snapshot_hash=snapshot_hash)

    def list_events(self, run_id: str) -> list[TraceEvent]:
        rows = self.conn.execute(
            """
            SELECT * FROM trace_events
            WHERE run_id = ?
            ORDER BY id ASC
            """,
            (run_id,),
        ).fetchall()
        return [
            TraceEvent(
                run_id=row["run_id"],
                event_id=row["event_id"],
                step_index=row["step_index"],
                source=row["source"],
                event_type=row["event_type"],
                tool_name=row["tool_name"],
                arguments=_load_json(row["arguments"]),
                result=_load_json(row["result"]),
                error=row["error"],
                state_hash_before=row["state_hash_before"],
                state_hash_after=row["state_hash_after"],
                tokens=row["tokens"],
                injected_fault=row["injected_fault"],
            )
            for row in rows
        ]

    def list_snapshots(self, run_id: str) -> list[DomainSnapshot]:
        rows = self.conn.execute(
            """
            SELECT snapshot_json FROM state_snapshots
            WHERE run_id = ?
            ORDER BY id ASC
            """,
            (run_id,),
        ).fetchall()
        return [
            DomainSnapshot.model_validate_json(row["snapshot_json"])
            for row in rows
        ]

    def timeline(self, run_id: str) -> list[dict[str, Any]]:
        """Replay a run as an ordered event list from the trace DB alone."""
        events = self.list_events(run_id)
        return [
            {
                "event_id": event.event_id,
                "step_index": event.step_index,
                "source": event.source,
                "event_type": event.event_type,
                "tool_name": event.tool_name,
                "arguments": event.arguments,
                "result": event.result,
                "error": event.error,
                "state_hash_before": event.state_hash_before,
                "state_hash_after": event.state_hash_after,
                "tokens": event.tokens,
                "injected_fault": event.injected_fault,
            }
            for event in events
        ]


def _dump_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, default=str, ensure_ascii=True)


def _load_json(raw: str | None) -> Any:
    if raw is None:
        return None
    return json.loads(raw)
