from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from loopmedic.runner.config import TOOL_CALL_CAP

FaultType = Literal[
    "pre_execution_timeout",
    "post_commit_response_loss",
    "stale_read",
    "transient_error",
]

READ_TOOLS = frozenset(
    {
        "get_customer",
        "list_customer_appointments",
        "search_available_slots",
        "get_appointment",
        "get_booking_policy",
    }
)
WRITE_TOOLS = frozenset(
    {
        "hold_slot",
        "release_hold",
        "create_appointment",
        "cancel_appointment",
        "send_confirmation",
    }
)
WRITE_ENTITY: dict[str, tuple[str, ...]] = {
    "hold_slot": ("customer_id", "slot_id"),
    "release_hold": ("hold_id",),
    "create_appointment": ("customer_id", "slot_id"),
    "cancel_appointment": ("appointment_id",),
    "send_confirmation": ("appointment_id",),
}
ALL_TOOLS = READ_TOOLS | WRITE_TOOLS

TIMEOUT_CODE = "timeout"
TIMEOUT_ERROR = "tool call timed out"
TRANSIENT_CODE = "transient_error"
TRANSIENT_ERROR = "transient error"


def timeout_payload() -> dict[str, Any]:
    """Agent-visible timeout. Identical for pre-execution and post-commit."""
    return {"ok": False, "code": TIMEOUT_CODE, "error": TIMEOUT_ERROR}


def transient_payload() -> dict[str, Any]:
    return {"ok": False, "code": TRANSIENT_CODE, "error": TRANSIENT_ERROR}


class FaultSpec(BaseModel):
    """Deterministic fault identity for one scenario.

    `seed` is the experiment-matching key (PLAN §7). These four faults
    are fully determined by type, tool, and trigger; the seed does not
    randomize them. Same spec ⇒ same payloads and world hashes.
    """

    fault_type: FaultType
    target_tool: str
    trigger_on_call: int = Field(ge=1, le=TOOL_CALL_CAP)
    seed: int = Field(ge=0)

    @model_validator(mode="after")
    def _compatible(self) -> FaultSpec:
        if self.target_tool not in ALL_TOOLS:
            raise ValueError(f"unknown target_tool {self.target_tool}")
        if self.fault_type == "stale_read":
            if self.target_tool not in READ_TOOLS:
                raise ValueError("stale_read requires a read tool")
            if self.trigger_on_call < 2:
                raise ValueError(
                    "stale_read requires trigger_on_call >= 2 "
                    "(a previous live answer for those arguments)"
                )
        if (
            self.fault_type == "post_commit_response_loss"
            and self.target_tool not in WRITE_TOOLS
        ):
            raise ValueError("post_commit_response_loss requires a write tool")
        return self


@dataclass(frozen=True)
class PassThrough:
    pass


@dataclass(frozen=True)
class SkipExecute:
    payload: dict[str, Any]
    fault: str


@dataclass(frozen=True)
class ReplaceAfterExecute:
    payload: dict[str, Any]
    fault: str


FaultAction = PassThrough | SkipExecute | ReplaceAfterExecute


@dataclass
class FaultInjector:
    """Seeded, deterministic faults applied after the intervention policy.

    Counts Allow-path calls to `target_tool` (1-based). One injector is
    bound to a single `run_id`. The agent-visible timeout text does not
    reveal whether the write committed; that is only in the ledger and
    in `injected_fault` on the trace event.
    """

    spec: FaultSpec
    _counts: dict[str, int] = field(default_factory=dict)
    _read_cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    _bound_run_id: str | None = field(default=None, init=False)

    def remember(
        self,
        tool: str,
        arguments: dict[str, Any],
        payload: dict[str, Any],
    ) -> None:
        if tool not in READ_TOOLS or payload.get("ok") is not True:
            return
        self._read_cache[_cache_key(tool, arguments)] = dict(payload)

    def consider(
        self,
        tool: str,
        arguments: dict[str, Any],
        run_id: str,
    ) -> FaultAction:
        self._bind(run_id)
        if tool != self.spec.target_tool:
            return PassThrough()
        self._counts[tool] = self._counts.get(tool, 0) + 1
        if self._counts[tool] != self.spec.trigger_on_call:
            return PassThrough()
        kind = self.spec.fault_type
        if kind == "pre_execution_timeout":
            return SkipExecute(timeout_payload(), kind)
        if kind == "post_commit_response_loss":
            return ReplaceAfterExecute(timeout_payload(), kind)
        if kind == "transient_error":
            return SkipExecute(transient_payload(), kind)
        if kind == "stale_read":
            cached = self._read_cache.get(_cache_key(tool, arguments))
            if cached is None:
                raise ValueError(
                    f"stale_read on {tool} has no previous live answer "
                    f"for arguments {arguments}"
                )
            return SkipExecute(dict(cached), kind)
        raise ValueError(f"unknown fault_type {kind}")

    def _bind(self, run_id: str) -> None:
        if self._bound_run_id is None:
            self._bound_run_id = run_id
            return
        if self._bound_run_id != run_id:
            raise RuntimeError(
                f"FaultInjector bound to run {self._bound_run_id}, "
                f"cannot be reused for {run_id}"
            )


def _cache_key(tool: str, arguments: dict[str, Any]) -> str:
    return json.dumps(
        {"tool": tool, **arguments},
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
