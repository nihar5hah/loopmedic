from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from loopmedic.evaluation.tasks import TaskSpec, booking_task, reschedule_task
from loopmedic.facade.faults import FaultSpec


class LoadedScenario(BaseModel):
    name: str
    task: TaskSpec
    fault: FaultSpec | None = None


def load_scenario(path: Path | str) -> LoadedScenario:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"scenario {path} is not a mapping")
    name = str(raw["name"])
    task = _task(raw.get("task") or {})
    fault = None
    if raw.get("fault") is not None:
        fault = FaultSpec.model_validate(raw["fault"])
    return LoadedScenario(name=name, task=task, fault=fault)


def _task(data: dict[str, Any]) -> TaskSpec:
    kind = str(data.get("kind") or "booking")
    overrides = {key: value for key, value in data.items() if key != "kind"}
    if kind == "booking":
        return booking_task(**overrides)
    if kind == "reschedule":
        return reschedule_task(**overrides)
    raise ValueError(f"unknown task kind {kind}")
