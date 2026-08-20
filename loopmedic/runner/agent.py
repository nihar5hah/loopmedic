from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agents import Agent, Model, RunContextWrapper, function_tool
from agents.mcp import MCPServer

from loopmedic.environment import service as domain
from loopmedic.runner.config import TOOL_CALL_CAP, ToolBudgetExceeded, build_model

INSTRUCTIONS = """
You are an appointment clerk for a fictional appliance-service shop.
Use the tools to read and change the booking database. Never invent
customer, slot, hold, or appointment ids — copy them from tool results.

Booking a new appointment:
1. Look up the customer.
2. Search available slots for the requested day and period.
3. Hold the chosen slot.
4. Create the appointment with that hold.
5. Send a confirmation for the new appointment.

Rescheduling:
1. Look up the customer and their existing appointments.
2. Search available slots for the requested day and period.
3. Hold the new slot.
4. Create the replacement appointment.
5. Cancel the original appointment.
6. Send a confirmation for the new appointment, not the cancelled one.

Creating an appointment does not consume the hold. Cancellation is
allowed. You have at most 15 tool calls. When finished, reply with a
short summary of what you did.
""".strip()


@dataclass
class BookingContext:
    conn: sqlite3.Connection
    run_id: str
    tool_calls: int = 0
    cap: int = TOOL_CALL_CAP
    calls: list[str] = field(default_factory=list)

    def charge(self, tool: str) -> None:
        self.tool_calls += 1
        self.calls.append(tool)
        if self.tool_calls > self.cap:
            raise ToolBudgetExceeded(self.cap)


def _ok(
    ctx: RunContextWrapper[BookingContext],
    tool: str,
    body: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    ctx.context.charge(tool)
    try:
        payload = body()
    except domain.DomainError as exc:
        return {"ok": False, "code": exc.code, "error": exc.message}
    return {"ok": True, **payload}


def _ids(
    ctx: RunContextWrapper[BookingContext],
    tool: str,
    *entity_parts: str,
) -> tuple[str, str]:
    return (
        domain.new_attempt_id(),
        domain.operation_fingerprint(ctx.context.run_id, tool, *entity_parts),
    )


@function_tool(failure_error_function=None)
async def get_customer(
    ctx: RunContextWrapper[BookingContext],
    customer_id: str,
) -> dict[str, Any]:
    """Look up a customer by id."""
    return _ok(
        ctx,
        "get_customer",
        lambda: domain.get_customer(ctx.context.conn, customer_id),
    )


@function_tool(failure_error_function=None)
async def list_customer_appointments(
    ctx: RunContextWrapper[BookingContext],
    customer_id: str,
) -> dict[str, Any]:
    """List appointments for a customer."""
    return _ok(
        ctx,
        "list_customer_appointments",
        lambda: domain.list_customer_appointments(
            ctx.context.conn,
            customer_id,
        ),
    )


@function_tool(failure_error_function=None)
async def search_available_slots(
    ctx: RunContextWrapper[BookingContext],
    day: str | None = None,
    period: str | None = None,
    service_type: str = "appliance",
) -> dict[str, Any]:
    """Search slots that still have remaining capacity."""
    return _ok(
        ctx,
        "search_available_slots",
        lambda: domain.search_available_slots(
            ctx.context.conn,
            day=day,
            period=period,
            service_type=service_type,
        ),
    )


@function_tool(failure_error_function=None)
async def get_appointment(
    ctx: RunContextWrapper[BookingContext],
    appointment_id: str,
) -> dict[str, Any]:
    """Look up an appointment by id."""
    return _ok(
        ctx,
        "get_appointment",
        lambda: domain.get_appointment(ctx.context.conn, appointment_id),
    )


@function_tool(failure_error_function=None)
async def get_booking_policy(
    ctx: RunContextWrapper[BookingContext],
) -> dict[str, Any]:
    """Return the stable booking policy document."""
    return _ok(
        ctx,
        "get_booking_policy",
        lambda: domain.get_booking_policy(ctx.context.conn),
    )


@function_tool(failure_error_function=None)
async def hold_slot(
    ctx: RunContextWrapper[BookingContext],
    customer_id: str,
    slot_id: str,
) -> dict[str, Any]:
    """Place a hold on a slot for a customer."""
    attempt_id, fingerprint = _ids(ctx, "hold_slot", customer_id, slot_id)
    return _ok(
        ctx,
        "hold_slot",
        lambda: domain.hold_slot(
            ctx.context.conn,
            customer_id,
            slot_id,
            attempt_id,
            fingerprint,
        ),
    )


@function_tool(failure_error_function=None)
async def release_hold(
    ctx: RunContextWrapper[BookingContext],
    hold_id: str,
) -> dict[str, Any]:
    """Release an existing hold."""
    attempt_id, fingerprint = _ids(ctx, "release_hold", hold_id)
    return _ok(
        ctx,
        "release_hold",
        lambda: domain.release_hold(
            ctx.context.conn,
            hold_id,
            attempt_id,
            fingerprint,
        ),
    )


@function_tool(failure_error_function=None)
async def create_appointment(
    ctx: RunContextWrapper[BookingContext],
    customer_id: str,
    slot_id: str,
    hold_id: str,
) -> dict[str, Any]:
    """Create a confirmed appointment from a live hold."""
    attempt_id, fingerprint = _ids(
        ctx,
        "create_appointment",
        customer_id,
        slot_id,
    )
    return _ok(
        ctx,
        "create_appointment",
        lambda: domain.create_appointment(
            ctx.context.conn,
            customer_id,
            slot_id,
            hold_id,
            attempt_id,
            fingerprint,
        ),
    )


@function_tool(failure_error_function=None)
async def cancel_appointment(
    ctx: RunContextWrapper[BookingContext],
    appointment_id: str,
    expected_version: int | None = None,
) -> dict[str, Any]:
    """Cancel a confirmed appointment. expected_version is optional."""
    attempt_id, fingerprint = _ids(
        ctx,
        "cancel_appointment",
        appointment_id,
    )
    return _ok(
        ctx,
        "cancel_appointment",
        lambda: domain.cancel_appointment(
            ctx.context.conn,
            appointment_id,
            attempt_id,
            fingerprint,
            expected_version=expected_version,
        ),
    )


@function_tool(failure_error_function=None)
async def send_confirmation(
    ctx: RunContextWrapper[BookingContext],
    appointment_id: str,
) -> dict[str, Any]:
    """Send a confirmation for an existing appointment."""
    attempt_id, fingerprint = _ids(ctx, "send_confirmation", appointment_id)
    return _ok(
        ctx,
        "send_confirmation",
        lambda: domain.send_confirmation(
            ctx.context.conn,
            appointment_id,
            attempt_id,
            fingerprint,
        ),
    )


def booking_tools() -> list[Any]:
    return [
        get_customer,
        list_customer_appointments,
        search_available_slots,
        get_appointment,
        get_booking_policy,
        hold_slot,
        release_hold,
        create_appointment,
        cancel_appointment,
        send_confirmation,
    ]


def build_agent(
    *,
    model: Model | None = None,
    mcp_servers: list[MCPServer] | None = None,
) -> Agent[BookingContext]:
    servers = list(mcp_servers or [])
    if not servers:
        raise ValueError(
            "build_agent requires mcp_servers; agent runs must go through "
            "the facade (booking_tools() is for tool-name unit tests only)"
        )
    return Agent(
        name="booking-agent",
        instructions=INSTRUCTIONS,
        model=model if model is not None else build_model(),
        tools=[],
        mcp_servers=servers,
    )
