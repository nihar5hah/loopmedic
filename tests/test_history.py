from __future__ import annotations

from loopmedic.core.events import DomainSnapshot
from loopmedic.evaluation.history import evaluate_history
from loopmedic.evaluation.tasks import booking_task, reschedule_task

CUSTOMERS = [
    {
        "customer_id": "C001",
        "name": "Asha Patel",
        "timezone": "America/New_York",
        "service_plan": "standard",
    }
]
SLOTS = [
    {
        "slot_id": "S003",
        "service_type": "appliance",
        "day": "Tuesday",
        "period": "morning",
        "capacity": 2,
    },
    {
        "slot_id": "S006",
        "service_type": "appliance",
        "day": "Wednesday",
        "period": "afternoon",
        "capacity": 2,
    },
]


def _snap(
    appointments: list[dict],
    notifications: list[dict] | None = None,
    holds: list[dict] | None = None,
) -> DomainSnapshot:
    return DomainSnapshot(
        customers=CUSTOMERS,
        slots=SLOTS,
        appointments=appointments,
        holds=holds or [],
        notifications=notifications or [],
    )


def _old() -> dict:
    return {
        "appointment_id": "A001",
        "customer_id": "C001",
        "slot_id": "S003",
        "service_type": "appliance",
        "day": "Tuesday",
        "period": "morning",
        "status": "CONFIRMED",
        "version": 1,
    }


def _new() -> dict:
    return {
        "appointment_id": "A005",
        "customer_id": "C001",
        "slot_id": "S006",
        "service_type": "appliance",
        "day": "Wednesday",
        "period": "afternoon",
        "status": "CONFIRMED",
        "version": 1,
    }


def test_history_flags_duplicate_mid_run() -> None:
    duplicate = {**_new(), "appointment_id": "A006"}
    snapshots = [
        _snap([_old()]),
        _snap([_old(), _new()]),
        _snap([_old(), _new(), duplicate]),
    ]
    result = evaluate_history(snapshots, reschedule_task())
    assert result.checks["never_two_active_appointments"] is False
    assert result.passed is False


def test_history_flags_cancel_before_replacement() -> None:
    cancelled = {**_old(), "status": "CANCELLED"}
    snapshots = [
        _snap([_old()]),
        _snap([cancelled]),
        _snap([cancelled, _new()]),
    ]
    result = evaluate_history(snapshots, reschedule_task())
    assert (
        result.checks["old_never_cancelled_before_replacement_existed"]
        is False
    )
    assert result.passed is False


def test_history_flags_confirmation_without_appointment() -> None:
    snapshots = [
        _snap(
            [_old()],
            notifications=[
                {
                    "notification_id": "N001",
                    "customer_id": "C001",
                    "appointment_id": "A999",
                    "type": "confirmation",
                }
            ],
        )
    ]
    result = evaluate_history(snapshots, reschedule_task())
    assert result.checks["no_confirmation_without_appointment"] is False
    assert result.passed is False


def test_clean_reschedule_history_passes() -> None:
    cancelled = {**_old(), "status": "CANCELLED"}
    snapshots = [
        _snap([_old()]),
        _snap([_old(), _new()]),
        _snap([cancelled, _new()]),
        _snap(
            [cancelled, _new()],
            notifications=[
                {
                    "notification_id": "N007",
                    "customer_id": "C001",
                    "appointment_id": "A005",
                    "type": "confirmation",
                }
            ],
        ),
    ]
    result = evaluate_history(snapshots, reschedule_task())
    assert result.passed is True


def test_booking_skips_old_appointment_history_check() -> None:
    result = evaluate_history([_snap([])], booking_task())
    assert "old_never_cancelled_before_replacement_existed" not in result.checks
    assert result.passed is True
