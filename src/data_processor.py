"""Validation and data-quality enrichment for farm IoT telemetry.

Adapted from the feature/iot-data branch. Raw sensor measurements are never
silently overwritten; quality flags are stored alongside the original values.
"""

from __future__ import annotations

import time
from typing import Any


SENSOR_RANGES: dict[str, dict[str, tuple[float, float]]] = {
    "SOIL_01": {"soil_moisture": (0, 100), "temperature": (-10, 60)},
    "WEATHER_01": {"temperature": (-20, 55), "humidity": (0, 100)},
    "PUMP_01": {"flow_rate": (0, 200), "power": (0, 5000), "pump_status": (0, 1)},
    "PH_01": {"ph": (0, 14)},
    "TANK_01": {"level": (0, 100)},
    "SUN_01": {"lux": (0, 150_000)},
}

WARNING_RANGES: dict[str, dict[str, tuple[float, float]]] = {
    "SOIL_01": {"soil_moisture": (10, 90), "temperature": (0, 50)},
    "WEATHER_01": {"temperature": (-10, 50), "humidity": (10, 95)},
    "PUMP_01": {"flow_rate": (1, 150), "power": (50, 4000), "pump_status": (1, 1)},
    "PH_01": {"ph": (4, 10)},
    "TANK_01": {"level": (5, 95)},
    "SUN_01": {"lux": (0, 120_000)},
}

VALID_DEVICES = frozenset(SENSOR_RANGES)


class IoTDataProcessor:
    """Validates telemetry and attaches freshness, range and anomaly evidence."""

    def __init__(self, stale_after_seconds: int = 60, future_tolerance_seconds: int = 60) -> None:
        self.stale_after_seconds = stale_after_seconds
        self.future_tolerance_seconds = future_tolerance_seconds

    def validate_payload(self, raw: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        device = raw.get("device_code")
        if device is None:
            errors.append("Missing device_code")
        elif device not in VALID_DEVICES:
            errors.append(f"Unknown device_code: {device}")
        metrics = raw.get("metrics")
        if not isinstance(metrics, dict) or not metrics:
            errors.append("metrics must be a non-empty object")
        elif any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in metrics.values()):
            errors.append("all metrics must be numeric")
        timestamp = raw.get("timestamp")
        if timestamp is not None and (not isinstance(timestamp, (int, float)) or timestamp < 0):
            errors.append("timestamp must be a non-negative number")
        return errors

    def check_ranges(self, device_code: str, metrics: dict[str, float]) -> dict[str, list[dict[str, Any]]]:
        valid: list[dict[str, Any]] = []
        out_of_range: list[dict[str, Any]] = []
        ranges = SENSOR_RANGES.get(device_code, {})
        for metric, value in metrics.items():
            bounds = ranges.get(metric)
            entry: dict[str, Any] = {"metric": metric, "value": value}
            if bounds is None:
                entry["range_check"] = "NOT_DEFINED"
                valid.append(entry)
                continue
            entry.update({"min": bounds[0], "max": bounds[1]})
            (valid if bounds[0] <= value <= bounds[1] else out_of_range).append(entry)
        return {"valid": valid, "out_of_range": out_of_range}

    def compute_freshness(self, timestamp: float | None, now: float | None = None) -> str:
        if timestamp is None:
            return "MISSING"
        age = (now or time.time()) - timestamp
        if age < -self.future_tolerance_seconds:
            return "INVALID_FUTURE"
        return "FRESH" if age <= self.stale_after_seconds else "STALE"

    def detect_anomalies(self, device_code: str, metrics: dict[str, float]) -> list[dict[str, Any]]:
        anomalies: list[dict[str, Any]] = []
        for metric, value in metrics.items():
            bounds = WARNING_RANGES.get(device_code, {}).get(metric)
            if bounds is not None and not bounds[0] <= value <= bounds[1]:
                anomalies.append({"metric": metric, "value": value, "expected_min": bounds[0], "expected_max": bounds[1], "severity": "WARNING"})
        return anomalies

    def process(self, raw_payload: dict[str, Any]) -> dict[str, Any]:
        errors = self.validate_payload(raw_payload)
        if errors:
            raise ValueError(f"Invalid payload: {'; '.join(errors)}")
        device_code = raw_payload["device_code"]
        metrics = dict(raw_payload["metrics"])
        timestamp = float(raw_payload.get("timestamp", time.time()))
        range_result = self.check_ranges(device_code, metrics)
        anomalies = self.detect_anomalies(device_code, metrics)
        freshness = self.compute_freshness(timestamp)
        return {
            "device_code": device_code,
            "timestamp": timestamp,
            "metrics": metrics,
            "quality": {
                "freshness": freshness,
                "anomalies": anomalies,
                "out_of_range": range_result["out_of_range"],
                "valid": not range_result["out_of_range"] and freshness not in {"MISSING", "INVALID_FUTURE"},
            },
            "received_at": time.time(),
        }
