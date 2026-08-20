from __future__ import annotations

import asyncio

from spikes.completion_rejection import CONTINUED, TASK_COMPLETE, run_spike


def test_rejected_completion_can_continue() -> None:
    rejected, continued = asyncio.run(run_spike())
    assert rejected.strip() == TASK_COMPLETE
    assert continued.strip() == CONTINUED
