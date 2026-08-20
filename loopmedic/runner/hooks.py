from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from agents import Agent, RunHooks, RunContextWrapper, Tool
from agents.items import ModelResponse, TResponseInputItem
from agents.tool_context import ToolContext

from loopmedic.core.state_hash import hash_snapshot, hash_world, snapshot_world
from loopmedic.core.trace_store import TraceStore
from loopmedic.environment.service import current_step
from loopmedic.runner.agent import BookingContext


@dataclass
class _OpenCall:
    call_id: str
    tool_name: str
    arguments: Any
    hash_before: str
    step_index: int


class TraceHooks(RunHooks[BookingContext]):
    """Record harness lifecycle events into a per-run trace database."""

    def __init__(
        self,
        store: TraceStore,
        *,
        record_tools: bool = False,
    ) -> None:
        self.store = store
        self.record_tools = record_tools
        self._open: dict[str, _OpenCall] = {}

    def fail_open_calls(self, booking: BookingContext, error: str) -> None:
        """Close any tool_proposed that never reached on_tool_end."""
        snapshot = snapshot_world(booking.conn)
        after = hash_snapshot(snapshot)
        for call in list(self._open.values()):
            self.store.emit(
                booking.run_id,
                "tool_failed",
                step_index=call.step_index,
                tool_name=call.tool_name,
                arguments=call.arguments,
                error=error,
                state_hash_before=call.hash_before,
                state_hash_after=after,
                snapshot=snapshot,
                snapshot_hash=after,
            )
        self._open.clear()

    async def on_llm_start(
        self,
        context: RunContextWrapper[BookingContext],
        agent: Agent[BookingContext],
        system_prompt: str | None,
        input_items: list[TResponseInputItem],
    ) -> None:
        del agent, system_prompt, input_items
        booking = context.context
        self.store.emit(
            booking.run_id,
            "llm_started",
            step_index=current_step(booking.conn),
        )

    async def on_llm_end(
        self,
        context: RunContextWrapper[BookingContext],
        agent: Agent[BookingContext],
        response: ModelResponse,
    ) -> None:
        del agent
        booking = context.context
        tokens = getattr(response.usage, "total_tokens", None)
        self.store.emit(
            booking.run_id,
            "llm_completed",
            step_index=current_step(booking.conn),
            tokens=tokens,
        )

    async def on_tool_start(
        self,
        context: RunContextWrapper[BookingContext],
        agent: Agent[BookingContext],
        tool: Tool,
    ) -> None:
        del agent
        if not self.record_tools:
            return
        booking = context.context
        before = hash_world(booking.conn)
        call_id = _call_id(context, tool)
        arguments = _tool_arguments(context)
        self._open[call_id] = _OpenCall(
            call_id=call_id,
            tool_name=_tool_name(context, tool),
            arguments=arguments,
            hash_before=before,
            step_index=current_step(booking.conn),
        )
        self.store.emit(
            booking.run_id,
            "tool_proposed",
            step_index=current_step(booking.conn),
            tool_name=_tool_name(context, tool),
            arguments=arguments,
            state_hash_before=before,
        )

    async def on_tool_end(
        self,
        context: RunContextWrapper[BookingContext],
        agent: Agent[BookingContext],
        tool: Tool,
        result: object,
    ) -> None:
        del agent
        if not self.record_tools:
            return
        booking = context.context
        snapshot = snapshot_world(booking.conn)
        after = hash_snapshot(snapshot)
        call_id = _call_id(context, tool)
        opened = self._open.pop(call_id, None)
        before = None if opened is None else opened.hash_before
        payload = _as_jsonable(result)
        failed = isinstance(payload, dict) and payload.get("ok") is False
        error = None
        if failed:
            error = str(payload.get("error") or payload.get("code") or "")
        self.store.emit(
            booking.run_id,
            "tool_failed" if failed else "tool_completed",
            step_index=current_step(booking.conn),
            tool_name=_tool_name(context, tool),
            arguments=_tool_arguments(context),
            result=payload,
            error=error,
            state_hash_before=before,
            state_hash_after=after,
            snapshot=snapshot,
            snapshot_hash=after,
        )

    async def on_agent_end(
        self,
        context: RunContextWrapper[BookingContext],
        agent: Agent[BookingContext],
        output: Any,
    ) -> None:
        del agent
        booking = context.context
        self.store.emit(
            booking.run_id,
            "final_output_proposed",
            step_index=current_step(booking.conn),
            result=_as_jsonable(output),
        )


def _tool_name(context: RunContextWrapper[BookingContext], tool: Tool) -> str:
    name = getattr(context, "tool_name", None)
    if isinstance(name, str) and name:
        return name
    return str(getattr(tool, "name", tool))


def _call_id(context: RunContextWrapper[BookingContext], tool: Tool) -> str:
    call_id = getattr(context, "tool_call_id", None)
    if isinstance(call_id, str) and call_id:
        return call_id
    return _tool_name(context, tool)


def _tool_arguments(context: RunContextWrapper[BookingContext]) -> Any:
    if not isinstance(context, ToolContext):
        return None
    raw = context.tool_arguments
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _as_jsonable(value: object) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _as_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_as_jsonable(item) for item in value]
    return str(value)
