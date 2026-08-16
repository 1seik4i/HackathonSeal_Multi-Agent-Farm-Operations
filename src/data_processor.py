"""Data Processing Pipeline for IoT telemetry.

TV1 — IoT & Data Engineer
Validates, cleans, and enriches raw sensor data before storage and
handoff to TV2 (AI Agents).

Pipeline steps:
    1. Validate  — device_code, metrics, timestamp
    2. Range     — metrics within physical bounds
    3. Freshness — FRESH / STALE / MISSING
    4. Anomaly   — flag values outside expected operating range
    5. Output    — ProcessedTelemetry dict ready for TV2
"""

from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sensor range definitions (min, max) per device + metric
# ---------------------------------------------------------------------------
SENSOR_RANGES: dict[str, dict[str, tuple[float, float]]] = {
    "SOIL_01": {
        "soil_moisture": (0, 100),       # %
        "temperature": (-10, 60),        # °C
    },
    "WEATHER_01": {
        "temperature": (-20, 55),        # °C
        "humidity": (0, 100),            # %
    },
    "PUMP_01": {
        "flow_rate": (0, 200),           # L/min
        "power": (0, 5000),              # W
    },
    "PH_01": {
        "ph": (0, 14),
    },
    "TANK_01": {
        "level": (0, 100),              # %
    },
    "SUN_01": {
        "lux": (0, 150_000),            # lux
    },
}

VALID_DEVICES = frozenset(SENSOR_RANGES.keys())

# Default freshness threshold — overridden at runtime from settings
_DEFAULT_STALE_SECONDS = 300


class IoTDataProcessor:
    """Transforms raw IoT payloads into validated, enriched telemetry."""

    def __init__(self, stale_after_seconds: int = _DEFAULT_STALE_SECONDS) -> None:
        self.stale_after_seconds = stale_after_seconds

    # ------------------------------------------------------------------
    # Step 1: Validate
    # ------------------------------------------------------------------
    def validate_payload(self, raw: dict[str, Any]) -> list[str]:
        """Return a list of validation error strings (empty == valid)."""
        errors: list[str] = []

        device = raw.get("device_code")
        if device is None:
            errors.append("Missing device_code")
        elif device not in VALID_DEVICES:
            errors.append(f"Unknown device_code: {device}")

        metrics = raw.get("metrics")
        if metrics is None:
            errors.append("Missing metrics")
        elif not isinstance(metrics, dict) or len(metrics) == 0:
            errors.append("metrics must be a non-empty dict")

        ts = raw.get("timestamp")
        if ts is not None:
            if not isinstance(ts, (int, float)):
                errors.append(f"timestamp must be numeric, got {type(ts).__name__}")
            elif ts < 0:
                errors.append("timestamp must be non-negative")

        return errors

    # ------------------------------------------------------------------
    # Step 2: Range check
    # ------------------------------------------------------------------
    def check_ranges(
        self, device_code: str, metrics: dict[str, float]
    ) -> dict[str, Any]:
        """Check each metric against known physical bounds.

        Returns ``{"valid": [...], "out_of_range": [...]}`` where each
        entry is ``{"metric": ..., "value": ..., "min": ..., "max": ...}``.
        """
        ranges = SENSOR_RANGES.get(device_code, {})
        valid: list[dict[str, Any]] = []
        out_of_range: list[dict[str, Any]] = []

        for metric, value in metrics.items():
            bounds = ranges.get(metric)
            entry = {"metric": metric, "value": value}
            if bounds is None:
                # Unknown metric — accept but don't range-check
                valid.append(entry)
                continue
            lo, hi = bounds
            entry["min"] = lo
            entry["max"] = hi
            if lo <= value <= hi:
                valid.append(entry)
            else:
                out_of_range.append(entry)

        return {"valid": valid, "out_of_range": out_of_range}

    # ------------------------------------------------------------------
    # Step 3: Freshness
    # ------------------------------------------------------------------
    def compute_freshness(self, timestamp: float | None) -> str:
        """Return FRESH, STALE, or MISSING."""
        if timestamp is None:
            return "MISSING"
        age = time.time() - timestamp
        return "FRESH" if age <= self.stale_after_seconds else "STALE"

    # ------------------------------------------------------------------
    # Step 4: Anomaly detection
    # ------------------------------------------------------------------
    def detect_anomalies(
        self, device_code: str, metrics: dict[str, float]
    ) -> list[dict[str, Any]]:
        """Flag metrics that are outside expected operating ranges.

        For now this mirrors range-check with tighter "warning" thresholds.
        Future: compare with rolling average from MongoDB history.
        """
        anomalies: list[dict[str, Any]] = []
        # Warning thresholds — narrower than physical limits
        warning_thresholds: dict[str, dict[str, tuple[float, float]]] = {
            "SOIL_01": {"soil_moisture": (10, 90), "temperature": (0, 50)},
            "WEATHER_01": {"temperature": (-10, 50), "humidity": (10, 95)},
            "PUMP_01": {"flow_rate": (1, 150), "power": (50, 4000)},
            "PH_01": {"ph": (4, 10)},
            "TANK_01": {"level": (5, 95)},
            "SUN_01": {"lux": (0, 120_000)},
        }
        thresholds = warning_thresholds.get(device_code, {})
        for metric, value in metrics.items():
            bounds = thresholds.get(metric)
            if bounds is None:
                continue
            lo, hi = bounds
            if value < lo or value > hi:
                anomalies.append({
                    "metric": metric,
                    "value": value,
                    "expected_min": lo,
                    "expected_max": hi,
                    "severity": "WARNING",
                })
        return anomalies

    # ------------------------------------------------------------------
    # Step 5: Full pipeline
    # ------------------------------------------------------------------
    def process(self, raw_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the complete pipeline.

        Returns a ``ProcessedTelemetry`` dict or raises ``ValueError``
        for fatally invalid payloads.
        """
        # --- validate ---
        errors = self.validate_payload(raw_payload)
        if errors:
            log.warning("Payload validation failed: %s", errors)
            raise ValueError(f"Invalid payload: {'; '.join(errors)}")

        device_code: str = raw_payload["device_code"]
        metrics: dict[str, float] = raw_payload["metrics"]
        timestamp: float = raw_payload.get("timestamp", time.time())

        # --- range check ---
        range_result = self.check_ranges(device_code, metrics)
        out_of_range = range_result["out_of_range"]
        if out_of_range:
            log.warning(
                "Out-of-range values for %s: %s", device_code, out_of_range
            )

        # --- freshness ---
        freshness = self.compute_freshness(timestamp)

        # --- anomaly detection ---
        anomalies = self.detect_anomalies(device_code, metrics)
        if anomalies:
            log.info("Anomalies detected for %s: %s", device_code, anomalies)

        # --- clean metrics: clamp out-of-range to bounds ---
        cleaned_metrics = dict(metrics)
        ranges = SENSOR_RANGES.get(device_code, {})
        for item in out_of_range:
            m = item["metric"]
            lo, hi = ranges.get(m, (item["value"], item["value"]))
            cleaned_metrics[m] = max(lo, min(hi, metrics[m]))
            log.info(
                "Clamped %s.%s from %.2f to %.2f",
                device_code, m, metrics[m], cleaned_metrics[m],
            )

        # --- build output ---
        valid = len(errors) == 0 and len(out_of_range) == 0
        return {
            "device_code": device_code,
            "timestamp": timestamp,
            "metrics": cleaned_metrics,
            "quality": {
                "freshness": freshness,
                "anomalies": anomalies,
                "out_of_range": out_of_range,
                "valid": valid,
            },
            "received_at": time.time(),
            "raw_payload": raw_payload,
        }
