from __future__ import annotations

from collections.abc import Callable, Sequence

from pydantic import BaseModel

from loopmedic.core.events import DomainSnapshot
from loopmedic.evaluation.tasks import TaskSpec

HistoryFn = Callable[[Sequence[DomainSnapshot], TaskSpec], bool]


class HistoryResult(BaseModel):
    passed: bool
    checks: dict[str, bool]


def never_two_active_appointments(
    snapshots: Sequence[DomainSnapshot],
    task: TaskSpec,
) -> bool:
    """Fail if a customer has two CONFIRMED rows on the same slot.

    A clean reschedule is allowed to overlap old and replacement on
    different slots; the duplicate-booking failure is a second write to
    the same customer+slot.
    """
    for snapshot in snapshots:
        seen: set[str] = set()
        for row in snapshot.appointments:
            if row["customer_id"] != task.customer_id:
                continue
            if row["status"] != "CONFIRMED":
                continue
            slot_id = str(row["slot_id"])
            if slot_id in seen:
                return False
            seen.add(slot_id)
    return True


def old_never_cancelled_before_replacement_existed(
    snapshots: Sequence[DomainSnapshot],
    task: TaskSpec,
) -> bool:
    original_id = task.original_appointment_id
    if original_id is None:
        return True
    replacement_seen = False
    for snapshot in snapshots:
        if _has_replacement(snapshot, task, original_id):
            replacement_seen = True
        old = _appointment(snapshot, original_id)
        if old is not None and old["status"] == "CANCELLED":
            if not replacement_seen:
                return False
    return True


def no_confirmation_without_appointment(
    snapshots: Sequence[DomainSnapshot],
    task: TaskSpec,
) -> bool:
    del task
    for snapshot in snapshots:
        appointment_ids = {
            row["appointment_id"] for row in snapshot.appointments
        }
        for note in snapshot.notifications:
            if note["appointment_id"] not in appointment_ids:
                return False
    return True


HISTORY_INVARIANTS: dict[str, HistoryFn] = {
    "never_two_active_appointments": never_two_active_appointments,
    "old_never_cancelled_before_replacement_existed": (
        old_never_cancelled_before_replacement_existed
    ),
    "no_confirmation_without_appointment": no_confirmation_without_appointment,
}


def evaluate_history(
    snapshots: Sequence[DomainSnapshot],
    task: TaskSpec,
) -> HistoryResult:
    checks = {
        name: fn(snapshots, task) for name, fn in HISTORY_INVARIANTS.items()
    }
    if task.original_appointment_id is None:
        checks.pop("old_never_cancelled_before_replacement_existed")
    return HistoryResult(passed=all(checks.values()), checks=checks)


def _appointment(
    snapshot: DomainSnapshot,
    appointment_id: str,
) -> dict[str, object] | None:
    for row in snapshot.appointments:
        if row["appointment_id"] == appointment_id:
            return row
    return None


def _has_replacement(
    snapshot: DomainSnapshot,
    task: TaskSpec,
    original_id: str,
) -> bool:
    return any(
        row["customer_id"] == task.customer_id
        and row["appointment_id"] != original_id
        and row["status"] == "CONFIRMED"
        and row["day"] == task.requested_day
        and row["period"] == task.requested_period
        for row in snapshot.appointments
    )
