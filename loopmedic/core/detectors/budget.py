from __future__ import annotations

from typing import Any

from loopmedic.core.detectors.base import DetectorHit
from loopmedic.core.events import TraceEvent
from loopmedic.core.features import FeatureState

NAME = "budget"
# Phase 9 may add a token cap. Until then this is tool-call fraction only.
THRESHOLD = 0.8


def check(
    event: TraceEvent,
    features: FeatureState,
    **_: Any,
) -> DetectorHit | None:
    if event.event_type != "tool_proposed":
        return None
    if features.cap <= 0:
        return None
    fraction = features.tool_calls / features.cap
    if fraction < THRESHOLD:
        return None
    return DetectorHit(
        detector=NAME,
        evidence={
            "tool_calls": features.tool_calls,
            "cap": features.cap,
            "fraction": fraction,
            "tokens": features.tokens,
        },
    )
