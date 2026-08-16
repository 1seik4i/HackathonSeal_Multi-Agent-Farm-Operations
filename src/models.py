from __future__ import annotations

from time import time
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


DeviceCode = Literal["SOIL_01", "WEATHER_01", "PUMP_01", "PH_01", "TANK_01", "SUN_01"]
Provider = Literal["openai", "gemini", "anthropic", "deepseek"]
ActionStatus = Literal["PENDING_APPROVAL", "APPROVED", "REJECTED", "EXECUTING", "VERIFIED", "FAILED", "CREATED"]


class TelemetryMessage(BaseModel):
    """Accepts either flat MQTT metrics or a metrics object from the contest feed."""

    device_code: DeviceCode
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


class AgentConfigRequest(BaseModel):
    provider: Provider
    model: str = Field(min_length=2, max_length=120)
    api_key: str = Field(min_length=8, max_length=1000)
    enabled: bool = True


class AgentConfigView(BaseModel):
    agent_id: str
    display_name: str
    role: str
    provider: Provider
    model: str
    enabled: bool
    has_api_key: bool
    connection_status: Literal["NOT_CONFIGURED", "TESTING", "READY", "FAILED"]
    last_tested_at: float | None = None
    last_error: str | None = None


class CoordinationRunRequest(BaseModel):
    scenario_text: str = Field(min_length=4, max_length=1200)
    selected_agents: list[str] = Field(min_length=1, max_length=5)
    target_zone: str = Field(default="FARM_ZONE_1", min_length=1, max_length=80)

    @field_validator("selected_agents")
    @classmethod
    def selected_agents_must_be_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("selected_agents must not contain duplicates")
        return value


class Evidence(BaseModel):
    device_code: str
    metric: str
    value: float | str
    freshness: Literal["FRESH", "STALE", "MISSING"]
    reason: str
    timestamp: float | None = None
    received_at: float | None = None
    source_type: Literal["MQTT", "DEMO", "API"] = "API"
    topic: str | None = None


class ActionRecord(BaseModel):
    id: str
    action_type: Literal["IRRIGATION_PLAN", "FIELD_TASK", "NOTIFICATION", "REPORT"]
    status: ActionStatus
    payload: dict[str, Any]
    created_at: float
    updated_at: float | None = None


class ApprovalRequest(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    operator_note: str = Field(default="", max_length=500)


class DemoSeedRequest(BaseModel):
    scenario: Literal["normal", "dry", "stale", "pump_failure"] = "dry"
