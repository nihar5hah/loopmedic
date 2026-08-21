from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from loopmedic.core.events import TraceEvent
from loopmedic.runner.config import TOOL_CALL_CAP

_ID_RE = re.compile(
    r"\b(?:[A-Z]\d{3}|[a-f0-9]{12,})\b",
    re.IGNORECASE,
)
TERMINAL = frozenset({"tool_completed", "tool_failed"})


def canonical_signature(tool: str | None, arguments: Any) -> str:
    return json.dumps(
        {"tool": tool, "args": arguments},
        sort_keys=True,
        default=str,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def normalize_error(event: TraceEvent) -> str:
    """Stable error identity: code plus message with ids stripped."""
    result = event.result if isinstance(event.result, dict) else {}
    code = str(result.get("code") or "")
    message = str(result.get("error") or event.error or "")
    return f"{code}:{_ID_RE.sub('<id>', message)}"


@dataclass
class FeatureState:
    """Rolling per-run features. Updated on every trace event."""

    cap: int = TOOL_CALL_CAP
    tool_calls: int = 0
    tokens: int = 0
    signature: str | None = None
    repeat_streak: int = 0
    error_streak: int = 0
    error_key: tuple[str, str, str] | None = None
    last_state_hash: str | None = None
    steps_unchanged: int = 0
    last_event_id: str | None = None
    last_tool: str | None = None
    last_arguments: Any = None
    last_normalized_error: str | None = None

    def observe(self, event: TraceEvent) -> None:
        self.last_event_id = event.event_id
        if event.event_type == "llm_completed" and event.tokens:
            self.tokens += int(event.tokens)
        if event.event_type == "run_started" and event.state_hash_after:
            self.last_state_hash = event.state_hash_after
            self.steps_unchanged = 0
            return
        if event.event_type == "tool_proposed":
            self.tool_calls += 1
            self.last_tool = event.tool_name
            self.last_arguments = event.arguments
            signature = canonical_signature(event.tool_name, event.arguments)
            if signature == self.signature:
                self.repeat_streak += 1
            else:
                self.signature = signature
                self.repeat_streak = 1
        if event.event_type not in TERMINAL:
            return
        after = event.state_hash_after
        if after is not None:
            if self.last_state_hash is not None and after == self.last_state_hash:
                self.steps_unchanged += 1
            else:
                self.steps_unchanged = 0
                self.last_state_hash = after
        if event.event_type != "tool_failed":
            self.error_key = None
            self.error_streak = 0
            self.last_normalized_error = None
            return
        unchanged = (
            event.state_hash_before is not None
            and event.state_hash_before == event.state_hash_after
        )
        if not unchanged:
            self.error_key = None
            self.error_streak = 0
            self.last_normalized_error = None
            return
        norm = normalize_error(event)
        signature = canonical_signature(event.tool_name, event.arguments)
        key = (norm, after or "", signature)
        self.last_normalized_error = norm
        if key == self.error_key:
            self.error_streak += 1
        else:
            self.error_key = key
            self.error_streak = 1
