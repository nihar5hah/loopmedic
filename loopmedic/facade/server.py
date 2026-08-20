from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.shared.exceptions import MCPError

from loopmedic.core.events import TraceEvent
from loopmedic.core.state_hash import hash_snapshot, hash_world, snapshot_world
from loopmedic.core.trace_store import TraceStore
from loopmedic.environment import service as domain
from loopmedic.environment.service import current_step
from loopmedic.facade.faults import (
    FaultInjector,
    PassThrough,
    ReplaceAfterExecute,
    SkipExecute,
)
from loopmedic.facade.policy import (
    Allow,
    AlwaysAllow,
    Block,
    Decision,
    InterventionPolicy,
    SubstituteResult,
)
from loopmedic.runner.agent import BookingContext
from loopmedic.runner.config import ToolBudgetExceeded

WRITE_ENTITY: dict[str, tuple[str, ...]] = {
    "hold_slot": ("customer_id", "slot_id"),
    "release_hold": ("hold_id",),
    "create_appointment": ("customer_id", "slot_id"),
    "cancel_appointment": ("appointment_id",),
    "send_confirmation": ("appointment_id",),
}


@dataclass
class FacadeContext:
    booking: BookingContext
    store: TraceStore
    policy: InterventionPolicy
    injector: FaultInjector | None = None
    last_injected_fault: str | None = None


def _ok(payload: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, **payload}


def _err(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "code": code, "error": message}


def _domain_err(exc: domain.DomainError) -> dict[str, Any]:
    return _err(exc.code, exc.message)


def _execute(conn: Any, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if tool in WRITE_ENTITY:
        attempt_id = domain.new_attempt_id()
        parts = tuple(str(arguments[name]) for name in WRITE_ENTITY[tool])
        fingerprint = domain.operation_fingerprint(
            arguments["_run_id"],
            tool,
            *parts,
        )
        return _dispatch_write(conn, tool, arguments, attempt_id, fingerprint)
    return _dispatch_read(conn, tool, arguments)


def _dispatch_read(
    conn: Any,
    tool: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    if tool == "get_customer":
        return domain.get_customer(conn, arguments["customer_id"])
    if tool == "list_customer_appointments":
        return domain.list_customer_appointments(conn, arguments["customer_id"])
    if tool == "search_available_slots":
        return domain.search_available_slots(
            conn,
            day=arguments.get("day"),
            period=arguments.get("period"),
            service_type=arguments.get("service_type", "appliance"),
        )
    if tool == "get_appointment":
        return domain.get_appointment(conn, arguments["appointment_id"])
    if tool == "get_booking_policy":
        return domain.get_booking_policy(conn)
    raise KeyError(f"unknown read tool {tool}")


def _dispatch_write(
    conn: Any,
    tool: str,
    arguments: dict[str, Any],
    attempt_id: str,
    fingerprint: str,
) -> dict[str, Any]:
    if tool == "hold_slot":
        return domain.hold_slot(
            conn,
            arguments["customer_id"],
            arguments["slot_id"],
            attempt_id,
            fingerprint,
            ttl_steps=int(arguments.get("ttl_steps") or domain.HOLD_TTL_STEPS),
        )
    if tool == "release_hold":
        return domain.release_hold(
            conn,
            arguments["hold_id"],
            attempt_id,
            fingerprint,
        )
    if tool == "create_appointment":
        return domain.create_appointment(
            conn,
            arguments["customer_id"],
            arguments["slot_id"],
            arguments["hold_id"],
            attempt_id,
            fingerprint,
        )
    if tool == "cancel_appointment":
        return domain.cancel_appointment(
            conn,
            arguments["appointment_id"],
            attempt_id,
            fingerprint,
            expected_version=arguments.get("expected_version"),
        )
    if tool == "send_confirmation":
        return domain.send_confirmation(
            conn,
            arguments["appointment_id"],
            attempt_id,
            fingerprint,
        )
    raise KeyError(f"unknown write tool {tool}")


def _handle(ctx: FacadeContext, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    booking = ctx.booking
    ctx.last_injected_fault = None
    before = hash_world(booking.conn)
    step = current_step(booking.conn)
    proposed = ctx.store.emit(
        booking.run_id,
        "tool_proposed",
        step_index=step,
        source="facade",
        tool_name=tool,
        arguments=arguments,
        state_hash_before=before,
    )
    try:
        booking.charge(tool)
        decision: Decision = ctx.policy.decide(proposed, booking)
        payload = _apply_decision(ctx, proposed, decision, arguments)
    except ToolBudgetExceeded as exc:
        payload = _err("tool_budget_exceeded", str(exc))
        _emit_terminal(ctx, proposed, payload)
        # Ordinary exceptions become MCP isError results and the agent can
        # keep calling. A protocol error is the cap's hard stop.
        raise MCPError(-32603, str(exc)) from exc
    except Exception as exc:
        # Recoverable faults (timeout, response-loss) and unexpected
        # handler errors must be tool results so the agent can retry.
        payload = _err("facade_error", f"{type(exc).__name__}: {exc}")
        _emit_terminal(ctx, proposed, payload)
        return payload
    _emit_terminal(ctx, proposed, payload)
    return payload


def _apply_decision(
    ctx: FacadeContext,
    proposed: TraceEvent,
    decision: Decision,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    booking = ctx.booking
    if isinstance(decision, Block):
        ctx.store.emit(
            booking.run_id,
            "intervention",
            step_index=current_step(booking.conn),
            source="facade",
            tool_name=proposed.tool_name,
            arguments=arguments,
            result={"action": "block", "feedback": decision.feedback},
        )
        return _err("blocked", decision.feedback)
    if isinstance(decision, SubstituteResult):
        ctx.store.emit(
            booking.run_id,
            "intervention",
            step_index=current_step(booking.conn),
            source="facade",
            tool_name=proposed.tool_name,
            arguments=arguments,
            result={"action": "substitute"},
        )
        return decision.result
    if not isinstance(decision, Allow):
        raise TypeError(f"unknown decision {decision!r}")
    action = PassThrough()
    if ctx.injector is not None:
        action = ctx.injector.consider(
            proposed.tool_name or "",
            arguments,
            booking.run_id,
        )
    if isinstance(action, SkipExecute):
        ctx.last_injected_fault = action.fault
        return action.payload
    bound = {**arguments, "_run_id": booking.run_id}
    try:
        executed = _execute(booking.conn, proposed.tool_name or "", bound)
    except domain.DomainError as exc:
        return _domain_err(exc)
    if isinstance(action, ReplaceAfterExecute):
        ctx.last_injected_fault = action.fault
        return action.payload
    payload = _ok(executed)
    if ctx.injector is not None:
        ctx.injector.remember(proposed.tool_name or "", arguments, payload)
    return payload


def _emit_terminal(
    ctx: FacadeContext,
    proposed: TraceEvent,
    payload: dict[str, Any],
) -> None:
    booking = ctx.booking
    snapshot = snapshot_world(booking.conn)
    after = hash_snapshot(snapshot)
    failed = payload.get("ok") is False
    ctx.store.emit(
        booking.run_id,
        "tool_failed" if failed else "tool_completed",
        step_index=current_step(booking.conn),
        source="facade",
        tool_name=proposed.tool_name,
        arguments=proposed.arguments,
        result=payload,
        error=None if not failed else str(payload.get("error") or payload.get("code") or ""),
        state_hash_before=proposed.state_hash_before,
        state_hash_after=after,
        snapshot=snapshot,
        snapshot_hash=after,
        injected_fault=ctx.last_injected_fault,
    )


def make_facade_server(
    booking: BookingContext,
    store: TraceStore,
    policy: InterventionPolicy | None = None,
    injector: FaultInjector | None = None,
) -> MCPServer:
    """Supervisory MCP facade. Calls the domain in-process, not via MCP."""
    ctx = FacadeContext(
        booking=booking,
        store=store,
        policy=policy or AlwaysAllow(),
        injector=injector,
    )
    server = MCPServer("loopmedic-facade")

    @server.tool()
    async def get_customer(customer_id: str) -> dict[str, Any]:
        """Look up a customer by id."""
        return _handle(ctx, "get_customer", {"customer_id": customer_id})

    @server.tool()
    async def list_customer_appointments(customer_id: str) -> dict[str, Any]:
        """List appointments for a customer."""
        return _handle(
            ctx,
            "list_customer_appointments",
            {"customer_id": customer_id},
        )

    @server.tool()
    async def search_available_slots(
        day: str | None = None,
        period: str | None = None,
        service_type: str = "appliance",
    ) -> dict[str, Any]:
        """Search slots that still have remaining capacity."""
        return _handle(
            ctx,
            "search_available_slots",
            {"day": day, "period": period, "service_type": service_type},
        )

    @server.tool()
    async def get_appointment(appointment_id: str) -> dict[str, Any]:
        """Look up an appointment by id."""
        return _handle(
            ctx,
            "get_appointment",
            {"appointment_id": appointment_id},
        )

    @server.tool()
    async def get_booking_policy() -> dict[str, Any]:
        """Return the stable booking policy document."""
        return _handle(ctx, "get_booking_policy", {})

    @server.tool()
    async def hold_slot(customer_id: str, slot_id: str) -> dict[str, Any]:
        """Place a hold on a slot for a customer."""
        return _handle(
            ctx,
            "hold_slot",
            {"customer_id": customer_id, "slot_id": slot_id},
        )

    @server.tool()
    async def release_hold(hold_id: str) -> dict[str, Any]:
        """Release an existing hold."""
        return _handle(ctx, "release_hold", {"hold_id": hold_id})

    @server.tool()
    async def create_appointment(
        customer_id: str,
        slot_id: str,
        hold_id: str,
    ) -> dict[str, Any]:
        """Create a confirmed appointment from a live hold."""
        return _handle(
            ctx,
            "create_appointment",
            {
                "customer_id": customer_id,
                "slot_id": slot_id,
                "hold_id": hold_id,
            },
        )

    @server.tool()
    async def cancel_appointment(
        appointment_id: str,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Cancel a confirmed appointment. expected_version is optional."""
        return _handle(
            ctx,
            "cancel_appointment",
            {
                "appointment_id": appointment_id,
                "expected_version": expected_version,
            },
        )

    @server.tool()
    async def send_confirmation(appointment_id: str) -> dict[str, Any]:
        """Send a confirmation for an existing appointment."""
        return _handle(
            ctx,
            "send_confirmation",
            {"appointment_id": appointment_id},
        )

    return server


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@asynccontextmanager
async def serve_facade(server: MCPServer) -> AsyncIterator[str]:
    port = _free_port()
    app = server.streamable_http_app(host="127.0.0.1")
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    http = uvicorn.Server(config)
    http.install_signal_handlers = False
    task = asyncio.create_task(http.serve())
    try:
        while not http.started:
            if task.done():
                raise RuntimeError(f"uvicorn exited before start: {task.exception()}")
            await asyncio.sleep(0.05)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        http.should_exit = True
        http.force_exit = True
        await task
        await asyncio.sleep(0)
