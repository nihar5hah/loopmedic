from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable

from loopmedic.core.events import TraceEvent
from loopmedic.core.features import FeatureState
from loopmedic.core.trace_store import TraceStore
from loopmedic.evaluation.tasks import TaskSpec
from loopmedic.runner.config import TOOL_CALL_CAP

from . import (
    budget,
    error_streak,
    premature,
    repetition,
    stagnation,
    unknown_commit,
)
from .base import DetectorHit

CheckFn = Callable[..., DetectorHit | None]
logger = logging.getLogger(__name__)

DETECTORS: tuple[tuple[str, CheckFn], ...] = (
    (repetition.NAME, repetition.check),
    (error_streak.NAME, error_streak.check),
    (stagnation.NAME, stagnation.check),
    (unknown_commit.NAME, unknown_commit.check),
    (premature.NAME, premature.check),
    (budget.NAME, budget.check),
)


def attach_detectors(
    store: TraceStore,
    conn: sqlite3.Connection,
    *,
    task: TaskSpec | None = None,
    cap: int = TOOL_CALL_CAP,
) -> FeatureState:
    """Evaluate detectors after every persisted event. Observe only."""
    features = FeatureState(cap=cap)

    def on_event(event: TraceEvent) -> None:
        try:
            features.observe(event)
        except Exception:
            return
        for name, check in DETECTORS:
            try:
                hit = check(event, features, conn=conn, task=task)
            except Exception:
                continue
            if hit is None:
                continue
            try:
                store.record_detector(
                    event.run_id,
                    event.event_id,
                    hit.detector or name,
                    evidence=hit.evidence,
                )
            except Exception:
                logger.warning(
                    "failed to persist detector %s for event %s",
                    hit.detector or name,
                    event.event_id,
                    exc_info=True,
                )

    store.add_listener(on_event)
    return features


__all__ = ["DETECTORS", "DetectorHit", "attach_detectors"]
