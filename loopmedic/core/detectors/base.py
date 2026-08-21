from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DetectorHit(BaseModel):
    detector: str
    evidence: dict[str, Any] = Field(default_factory=dict)
