from __future__ import annotations

import sqlite3
from typing import Any

from loopmedic.core.detectors.base import DetectorHit
from loopmedic.core.events import TraceEvent
from loopmedic.core.features import FeatureState
from loopmedic.evaluation.invariants import evaluate
from loopmedic.evaluation.tasks import TaskSpec

NAME = "premature_completion"


def check(
    event: TraceEvent,
    features: FeatureState,
    *,
    conn: sqlite3.Connection,
    task: TaskSpec | None = None,
    **_: Any,
) -> DetectorHit | None:
    del features
    if event.event_type != "final_output_proposed":
        return None
    if task is None:
        return None
    verdict = evaluate(conn, task)
    if verdict.passed:
        return None
    return DetectorHit(
        detector=NAME,
        evidence={
            "checks": verdict.checks,
            "output": event.result,
        },
    )
