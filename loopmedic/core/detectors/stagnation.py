from __future__ import annotations

from typing import Any

from loopmedic.core.detectors.base import DetectorHit
from loopmedic.core.events import TraceEvent
from loopmedic.core.features import FeatureState, TERMINAL

NAME = "stagnation"
# N=3 would fire on a clean reschedule's opening reads (get, list, search).
THRESHOLD = 5


def check(
    event: TraceEvent,
    features: FeatureState,
    **_: Any,
) -> DetectorHit | None:
    if event.event_type not in TERMINAL:
        return None
    if features.steps_unchanged < THRESHOLD:
        return None
    return DetectorHit(
        detector=NAME,
        evidence={
            "steps_unchanged": features.steps_unchanged,
            "state_hash": features.last_state_hash,
        },
    )
