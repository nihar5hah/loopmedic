from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from loopmedic.core.events import TraceEvent
from loopmedic.runner.agent import BookingContext


@dataclass(frozen=True)
class Allow:
    pass


@dataclass(frozen=True)
class Block:
    feedback: str


@dataclass(frozen=True)
class SubstituteResult:
    result: dict[str, Any]


Decision = Allow | Block | SubstituteResult


class InterventionPolicy(Protocol):
    def decide(
        self,
        pre_event: TraceEvent,
        run_state: BookingContext,
    ) -> Decision: ...


class AlwaysAllow:
    """Condition A: every call is forwarded to the environment."""

    def decide(
        self,
        pre_event: TraceEvent,
        run_state: BookingContext,
    ) -> Decision:
        del pre_event, run_state
        return Allow()
