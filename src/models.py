from __future__ import annotations

from time import time
from typing import Any, Literal

# pyrefly: ignore [missing-import]
from pydantic import BaseModel, Field, field_validator


class TelemetryMessage(BaseModel):
    """Accepts either flat MQTT metrics or a metrics object from the contest feed."""

    device_code: Literal["SOIL_01", "WEATHER_01", "PUMP_01", "PH_01", "TANK_01", "SUN_01"]
    timestamp: float = Field(default_factory=time)
    metrics: dict[str, float]

    @field_validator("metrics")
    @classmethod
    def metrics_must_not_be_empty(cls, value: dict[str, float]) -> dict[str, float]:
        if not value:
            raise ValueError("metrics must not be empty")
        return value


class ManagerRequest(BaseModel):
    request: str = Field(min_length=4, max_length=600)
    manager_name: str = "Farm Manager"


class Evidence(BaseModel):
    device_code: str
    device_id: str | None = None
    metric: str
    value: float | str
    freshness: Literal["FRESH", "STALE", "MISSING"]
    reason: str
    timestamp: float | None = None
    agent: str | None = None


class ActionRecord(BaseModel):
    id: str
    action_type: Literal["IRRIGATION_PLAN", "FIELD_TASK", "NOTIFICATION", "REPORT"]
    status: Literal["PENDING_APPROVAL", "CREATED", "VERIFIED"]
    payload: dict[str, Any]
    created_at: float

