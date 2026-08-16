"""Tests for IoTDataProcessor — TV1 data processing pipeline."""

from __future__ import annotations

import time

import pytest

from src.data_processor import IoTDataProcessor


@pytest.fixture
def processor():
    return IoTDataProcessor(stale_after_seconds=300)


# ======================================================================
# Validate
# ======================================================================
class TestValidate:
    def test_valid_payload(self, processor):
        raw = {"device_code": "SOIL_01", "metrics": {"soil_moisture": 30}, "timestamp": time.time()}
        assert processor.validate_payload(raw) == []

    def test_missing_device_code(self, processor):
        raw = {"metrics": {"soil_moisture": 30}}
        errors = processor.validate_payload(raw)
        assert any("device_code" in e.lower() for e in errors)

    def test_unknown_device(self, processor):
        raw = {"device_code": "FAKE_99", "metrics": {"val": 1}}
        errors = processor.validate_payload(raw)
        assert any("Unknown" in e for e in errors)

    def test_missing_metrics(self, processor):
        raw = {"device_code": "SOIL_01"}
        errors = processor.validate_payload(raw)
        assert any("metrics" in e.lower() for e in errors)

    def test_empty_metrics(self, processor):
        raw = {"device_code": "SOIL_01", "metrics": {}}
        errors = processor.validate_payload(raw)
        assert any("non-empty" in e for e in errors)

    def test_negative_timestamp(self, processor):
        raw = {"device_code": "SOIL_01", "metrics": {"soil_moisture": 30}, "timestamp": -1}
        errors = processor.validate_payload(raw)
        assert any("non-negative" in e for e in errors)


# ======================================================================
# Range check
# ======================================================================
class TestRangeCheck:
    def test_within_range(self, processor):
        result = processor.check_ranges("SOIL_01", {"soil_moisture": 50, "temperature": 25})
        assert len(result["out_of_range"]) == 0
        assert len(result["valid"]) == 2

    def test_out_of_range(self, processor):
        result = processor.check_ranges("SOIL_01", {"soil_moisture": 120})
        assert len(result["out_of_range"]) == 1
        assert result["out_of_range"][0]["metric"] == "soil_moisture"

    def test_negative_out_of_range(self, processor):
        result = processor.check_ranges("TANK_01", {"level": -5})
        assert len(result["out_of_range"]) == 1

    def test_unknown_metric_accepted(self, processor):
        result = processor.check_ranges("SOIL_01", {"unknown_metric": 999})
        assert len(result["valid"]) == 1
        assert len(result["out_of_range"]) == 0

    def test_boundary_values(self, processor):
        result = processor.check_ranges("PH_01", {"ph": 0})
        assert len(result["valid"]) == 1
        result = processor.check_ranges("PH_01", {"ph": 14})
        assert len(result["valid"]) == 1


# ======================================================================
# Freshness
# ======================================================================
class TestFreshness:
    def test_fresh(self, processor):
        assert processor.compute_freshness(time.time()) == "FRESH"

    def test_stale(self, processor):
        assert processor.compute_freshness(time.time() - 600) == "STALE"

    def test_missing(self, processor):
        assert processor.compute_freshness(None) == "MISSING"

    def test_boundary(self, processor):
        # Exactly at the threshold
        assert processor.compute_freshness(time.time() - 300) == "FRESH"
        assert processor.compute_freshness(time.time() - 301) == "STALE"


# ======================================================================
# Anomaly detection
# ======================================================================
class TestAnomalyDetection:
    def test_no_anomalies(self, processor):
        anomalies = processor.detect_anomalies("SOIL_01", {"soil_moisture": 40, "temperature": 30})
        assert anomalies == []

    def test_anomaly_detected(self, processor):
        anomalies = processor.detect_anomalies("TANK_01", {"level": 2})
        assert len(anomalies) == 1
        assert anomalies[0]["severity"] == "WARNING"

    def test_pump_zero_anomaly(self, processor):
        anomalies = processor.detect_anomalies("PUMP_01", {"flow_rate": 0, "power": 0})
        assert len(anomalies) == 2


# ======================================================================
# Full pipeline (process)
# ======================================================================
class TestProcess:
    def test_full_pipeline_normal(self, processor):
        raw = {
            "device_code": "SOIL_01",
            "timestamp": time.time(),
            "metrics": {"soil_moisture": 27.5, "temperature": 31.2},
        }
        result = processor.process(raw)
        assert result["device_code"] == "SOIL_01"
        assert result["quality"]["freshness"] == "FRESH"
        assert result["quality"]["valid"] is True
        assert "metrics" in result
        assert "received_at" in result

    def test_full_pipeline_stale(self, processor):
        raw = {
            "device_code": "WEATHER_01",
            "timestamp": time.time() - 600,
            "metrics": {"temperature": 32, "humidity": 55},
        }
        result = processor.process(raw)
        assert result["quality"]["freshness"] == "STALE"

    def test_full_pipeline_out_of_range_clamped(self, processor):
        raw = {
            "device_code": "SOIL_01",
            "timestamp": time.time(),
            "metrics": {"soil_moisture": 120},
        }
        result = processor.process(raw)
        assert result["metrics"]["soil_moisture"] == 100  # clamped
        assert result["quality"]["valid"] is False

    def test_full_pipeline_invalid_raises(self, processor):
        raw = {"device_code": "FAKE_99", "metrics": {"val": 1}}
        with pytest.raises(ValueError, match="Invalid payload"):
            processor.process(raw)

    def test_output_format_for_tv2(self, processor):
        """Ensure output matches what TV2 FieldIoTAgent expects."""
        raw = {
            "device_code": "PUMP_01",
            "timestamp": time.time(),
            "metrics": {"flow_rate": 18, "power": 430},
        }
        result = processor.process(raw)
        # TV2 expects: timestamp (float), metrics (dict), and now quality
        assert isinstance(result["timestamp"], float)
        assert isinstance(result["metrics"], dict)
        assert "quality" in result
        assert result["quality"]["freshness"] in ("FRESH", "STALE", "MISSING")
