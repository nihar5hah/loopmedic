from __future__ import annotations

from typing import Any

from loopmedic.core.detectors.base import DetectorHit
from loopmedic.core.events import TraceEvent
from loopmedic.core.features import FeatureState

NAME = "repetition"
THRESHOLD = 2


def check(
    event: TraceEvent,
    features: FeatureState,
    **_: Any,
) -> DetectorHit | None:
    if event.event_type != "tool_proposed":
        return None
    if features.repeat_streak < THRESHOLD:
        return None
    return DetectorHit(
        detector=NAME,
        evidence={
            "signature": features.signature,
            "streak": features.repeat_streak,
            "tool": event.tool_name,
        },
    )
