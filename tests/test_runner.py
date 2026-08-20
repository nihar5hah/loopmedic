from __future__ import annotations

import os

import pytest

from loopmedic.environment.service import connect
from loopmedic.evaluation.tasks import booking_task, reschedule_task
from loopmedic.runner.agent import BookingContext, booking_tools, build_agent
from loopmedic.runner.config import (
    DEFAULT_MODEL,
    TOOL_CALL_CAP,
    ToolBudgetExceeded,
    load_dotenv,
)


def test_default_model_is_deepseek_v4_flash() -> None:
    assert DEFAULT_MODEL == "deepseek-v4-flash"


def test_booking_tools_are_the_ten_domain_tools() -> None:
    names = {tool.name for tool in booking_tools()}
    assert names == {
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
    }


def test_tool_budget_allows_cap_then_raises() -> None:
    ctx = BookingContext(conn=connect(":memory:"), run_id="budget")
    for _ in range(TOOL_CALL_CAP):
        ctx.charge("get_customer")
    with pytest.raises(ToolBudgetExceeded):
        ctx.charge("get_customer")
    assert ctx.tool_calls == TOOL_CALL_CAP + 1


def test_build_agent_requires_facade_servers() -> None:
    with pytest.raises(ValueError, match="mcp_servers"):
        build_agent()


def test_booking_task_has_no_original_appointment() -> None:
    spec = booking_task()
    assert spec.customer_id == "C000"
    assert spec.original_appointment_id is None
    assert "old_appointment_cancelled" not in spec.required_invariants
    assert reschedule_task().original_appointment_id == "A001"


def test_dotenv_overwrites_keys_but_preserves_other_shell_values(
    tmp_path,
    monkeypatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENCODE_API_KEY=fromfile\nLOOPMEDIC_MODEL=fromfile\n",
        encoding="utf-8",
    )
    monkeypatch.setitem(os.environ, "OPENCODE_API_KEY", "fromshell")
    monkeypatch.setitem(os.environ, "LOOPMEDIC_MODEL", "fromshell")
    load_dotenv(paths=(env_file,))
    assert os.environ["OPENCODE_API_KEY"] == "fromfile"
    assert os.environ["LOOPMEDIC_MODEL"] == "fromshell"
