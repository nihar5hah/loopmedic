from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

EventSource = Literal["harness", "facade", "environment"]
EventType = Literal[
    "run_started",
    "llm_started",
    "llm_completed",
    "tool_proposed",
    "tool_completed",
    "tool_failed",
    "intervention",
    "final_output_proposed",
    "run_completed",
]


class TraceEvent(BaseModel):
    run_id: str
    event_id: str
    step_index: int
    source: EventSource
    event_type: EventType
    tool_name: str | None = None
    arguments: Any | None = None
    result: Any | None = None
    error: str | None = None
    state_hash_before: str | None = None
    state_hash_after: str | None = None
    tokens: int | None = None
    injected_fault: str | None = None


class DomainSnapshot(BaseModel):
    """Canonical world view used for hashing and history invariants.

    Ledger rows and raw step counters are omitted. Hold status is the
    derived ACTIVE/EXPIRED value at the current logical step.
    """

    customers: list[dict[str, Any]] = Field(default_factory=list)
    slots: list[dict[str, Any]] = Field(default_factory=list)
    appointments: list[dict[str, Any]] = Field(default_factory=list)
    holds: list[dict[str, Any]] = Field(default_factory=list)
    notifications: list[dict[str, Any]] = Field(default_factory=list)
