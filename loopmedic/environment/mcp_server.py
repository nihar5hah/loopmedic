from __future__ import annotations

import sqlite3
from typing import Any

from mcp.server.mcpserver import MCPServer

from loopmedic.environment import service as domain

TOOL_NAMES = (
    "get_customer",
    "list_customer_appointments",
    "search_available_slots",
    "get_appointment",
    "get_booking_policy",
    "hold_slot",
    "release_hold",
    "create_appointment",
    "cancel_appointment",
    "send_confirmation",
)


def _ok(payload: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, **payload}


def _err(exc: domain.DomainError) -> dict[str, Any]:
    return {"ok": False, "code": exc.code, "error": exc.message}


def make_appointment_server(
    conn: sqlite3.Connection,
    run_id: str = "run",
) -> MCPServer:
    """Domain MCP server. The facade replaces this wiring in Phase 4.

    run_id is folded into every write fingerprint; the facade must reuse
    the same value for that run. Handlers are async so MCP does not hop
    to a worker thread (sqlite3 connections are thread-bound).
    """
    server = MCPServer("appointments")

    def write_ids(tool: str, *entity_parts: str) -> tuple[str, str]:
        return (
            domain.new_attempt_id(),
            domain.operation_fingerprint(run_id, tool, *entity_parts),
        )

    @server.tool()
    async def get_customer(customer_id: str) -> dict[str, Any]:
        """Look up a customer by id."""
        try:
            return _ok(domain.get_customer(conn, customer_id))
        except domain.DomainError as exc:
            return _err(exc)

    @server.tool()
    async def list_customer_appointments(customer_id: str) -> dict[str, Any]:
        """List appointments for a customer."""
        try:
            return _ok(domain.list_customer_appointments(conn, customer_id))
        except domain.DomainError as exc:
            return _err(exc)

    @server.tool()
    async def search_available_slots(
        day: str | None = None,
        period: str | None = None,
        service_type: str = "appliance",
    ) -> dict[str, Any]:
        """Search slots that still have remaining capacity."""
        try:
            return _ok(
                domain.search_available_slots(
                    conn,
                    day=day,
                    period=period,
                    service_type=service_type,
                )
            )
        except domain.DomainError as exc:
            return _err(exc)

    @server.tool()
    async def get_appointment(appointment_id: str) -> dict[str, Any]:
        """Look up an appointment by id."""
        try:
            return _ok(domain.get_appointment(conn, appointment_id))
        except domain.DomainError as exc:
            return _err(exc)

    @server.tool()
    async def get_booking_policy() -> dict[str, Any]:
        """Return the stable booking policy document."""
        try:
            return _ok(domain.get_booking_policy(conn))
        except domain.DomainError as exc:
            return _err(exc)

    @server.tool()
    async def hold_slot(customer_id: str, slot_id: str) -> dict[str, Any]:
        """Place a hold on a slot for a customer."""
        attempt_id, fingerprint = write_ids(
            "hold_slot",
            customer_id,
            slot_id,
        )
        try:
            return _ok(
                domain.hold_slot(
                    conn,
                    customer_id,
                    slot_id,
                    attempt_id,
                    fingerprint,
                )
            )
        except domain.DomainError as exc:
            return _err(exc)

    @server.tool()
    async def release_hold(hold_id: str) -> dict[str, Any]:
        """Release an existing hold."""
        attempt_id, fingerprint = write_ids("release_hold", hold_id)
        try:
            return _ok(
                domain.release_hold(conn, hold_id, attempt_id, fingerprint)
            )
        except domain.DomainError as exc:
            return _err(exc)

    @server.tool()
    async def create_appointment(
        customer_id: str,
        slot_id: str,
        hold_id: str,
    ) -> dict[str, Any]:
        """Create a confirmed appointment from a live hold."""
        # hold_id is not part of the fingerprint (PLAN §3.1).
        attempt_id, fingerprint = write_ids(
            "create_appointment",
            customer_id,
            slot_id,
        )
        try:
            return _ok(
                domain.create_appointment(
                    conn,
                    customer_id,
                    slot_id,
                    hold_id,
                    attempt_id,
                    fingerprint,
                )
            )
        except domain.DomainError as exc:
            return _err(exc)

    @server.tool()
    async def cancel_appointment(
        appointment_id: str,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Cancel a confirmed appointment. expected_version is optional."""
        attempt_id, fingerprint = write_ids(
            "cancel_appointment",
            appointment_id,
        )
        try:
            return _ok(
                domain.cancel_appointment(
                    conn,
                    appointment_id,
                    attempt_id,
                    fingerprint,
                    expected_version=expected_version,
                )
            )
        except domain.DomainError as exc:
            return _err(exc)

    @server.tool()
    async def send_confirmation(appointment_id: str) -> dict[str, Any]:
        """Send a confirmation for an existing appointment."""
        attempt_id, fingerprint = write_ids(
            "send_confirmation",
            appointment_id,
        )
        try:
            return _ok(
                domain.send_confirmation(
                    conn,
                    appointment_id,
                    attempt_id,
                    fingerprint,
                )
            )
        except domain.DomainError as exc:
            return _err(exc)

    return server
