from __future__ import annotations

from typing import Any

from loopmedic.core.detectors.base import DetectorHit
from loopmedic.core.events import TraceEvent
from loopmedic.core.features import FeatureState

NAME = "error_streak"
THRESHOLD = 2


def check(
    event: TraceEvent,
    features: FeatureState,
    **_: Any,
) -> DetectorHit | None:
    if event.event_type != "tool_failed":
        return None
    if features.error_streak < THRESHOLD:
        return None
    return DetectorHit(
        detector=NAME,
        evidence={
            "normalized_error": features.last_normalized_error,
            "streak": features.error_streak,
            "tool": event.tool_name,
        },
    )
