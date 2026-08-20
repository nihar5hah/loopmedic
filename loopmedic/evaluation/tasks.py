from __future__ import annotations

from pydantic import BaseModel

RESCHEDULE_INVARIANTS = (
    "exactly_one_active_appointment",
    "new_appointment_matches_request",
    "old_appointment_cancelled",
    "confirmation_sent",
    "no_duplicate_booking_final",
)

BOOKING_INVARIANTS = (
    "exactly_one_active_appointment",
    "new_appointment_matches_request",
    "confirmation_sent",
    "no_duplicate_booking_final",
)


class TaskSpec(BaseModel):
    goal_text: str
    customer_id: str
    requested_day: str
    requested_period: str
    required_invariants: list[str]
    scenario_seed: int
    original_appointment_id: str | None = None


def reschedule_task(
    customer_id: str = "C001",
    requested_day: str = "Wednesday",
    requested_period: str = "afternoon",
    scenario_seed: int = 42,
    original_appointment_id: str = "A001",
) -> TaskSpec:
    goal = (
        f"Reschedule customer {customer_id}'s appointment to "
        f"{requested_day} {requested_period}. Create the replacement "
        "before cancelling the original, then send a confirmation."
    )
    return TaskSpec(
        goal_text=goal,
        customer_id=customer_id,
        requested_day=requested_day,
        requested_period=requested_period,
        required_invariants=list(RESCHEDULE_INVARIANTS),
        scenario_seed=scenario_seed,
        original_appointment_id=original_appointment_id,
    )


def booking_task(
    customer_id: str = "C000",
    requested_day: str = "Monday",
    requested_period: str = "morning",
    scenario_seed: int = 42,
) -> TaskSpec:
    goal = (
        f"Book a new appliance-service appointment for customer "
        f"{customer_id} on {requested_day} {requested_period}. "
        "Search for a slot, hold it, create the appointment, then send "
        "a confirmation."
    )
    return TaskSpec(
        goal_text=goal,
        customer_id=customer_id,
        requested_day=requested_day,
        requested_period=requested_period,
        required_invariants=list(BOOKING_INVARIANTS),
        scenario_seed=scenario_seed,
        original_appointment_id=None,
    )
