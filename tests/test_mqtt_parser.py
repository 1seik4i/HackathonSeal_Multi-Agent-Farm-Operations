"""Tests for MQTTIngestionClient._normalize — TV1 parser logic."""

from __future__ import annotations

import time

import pytest

from src.mqtt_client import MQTTIngestionClient


class TestNormalize:
    """Unit tests for the static _normalize helper."""

    def test_standard_payload(self):
        """Standard payload with device_code + float timestamp."""
        raw = {
            "device_code": "SOIL_01",
            "timestamp": 1723766400.0,
            "metrics": {"soil_moisture": 27.5, "temperature": 31.2},
        }
        msg = MQTTIngestionClient._normalize(raw)
        assert msg.device_code == "SOIL_01"
        assert msg.timestamp == 1723766400.0
        assert msg.metrics == {"soil_moisture": 27.5, "temperature": 31.2}

    def test_device_id_alias(self):
        """Payload using device_id instead of device_code."""
        raw = {
            "device_id": "WEATHER_01",
            "timestamp": 1723766401.0,
            "metrics": {"temperature": 35, "humidity": 48},
        }
        msg = MQTTIngestionClient._normalize(raw)
        assert msg.device_code == "WEATHER_01"

    def test_device_alias(self):
        """Payload using 'device' field."""
        raw = {
            "device": "PH_01",
            "metrics": {"ph": 6.4},
        }
        msg = MQTTIngestionClient._normalize(raw)
        assert msg.device_code == "PH_01"
        assert msg.metrics == {"ph": 6.4}

    def test_iso8601_timestamp(self):
        """ISO-8601 string timestamp is converted to float."""
        raw = {
            "device_code": "TANK_01",
            "timestamp": "2026-08-16T08:00:00Z",
            "metrics": {"level": 62},
        }
        msg = MQTTIngestionClient._normalize(raw)
        assert isinstance(msg.timestamp, float)
        assert msg.timestamp > 0

    def test_iso8601_with_timezone_offset(self):
        """ISO-8601 with explicit offset."""
        raw = {
            "device_code": "SUN_01",
            "timestamp": "2026-08-16T15:00:00+07:00",
            "metrics": {"lux": 78000},
        }
        msg = MQTTIngestionClient._normalize(raw)
        assert isinstance(msg.timestamp, float)

    def test_flat_payload_no_metrics_key(self):
        """Flat payload without explicit 'metrics' key."""
        raw = {
            "device_code": "PUMP_01",
            "flow_rate": 18,
            "power": 430,
        }
        msg = MQTTIngestionClient._normalize(raw)
        assert msg.device_code == "PUMP_01"
        assert msg.metrics == {"flow_rate": 18, "power": 430}

    def test_ts_alias(self):
        """Payload using 'ts' instead of 'timestamp'."""
        raw = {
            "device_code": "SOIL_01",
            "ts": 1723766400.0,
            "metrics": {"soil_moisture": 30},
        }
        msg = MQTTIngestionClient._normalize(raw)
        assert msg.timestamp == 1723766400.0

    def test_no_timestamp_gets_default(self):
        """Missing timestamp should get a default (current time)."""
        raw = {
            "device_code": "SOIL_01",
            "metrics": {"soil_moisture": 30},
        }
        before = time.time()
        msg = MQTTIngestionClient._normalize(raw)
        after = time.time()
        assert before <= msg.timestamp <= after

    def test_invalid_device_raises(self):
        """Unknown device_code should raise a validation error."""
        raw = {
            "device_code": "INVALID_99",
            "metrics": {"value": 1},
        }
        with pytest.raises(Exception):
            MQTTIngestionClient._normalize(raw)

    def test_empty_metrics_raises(self):
        """Empty metrics dict should raise a validation error."""
        raw = {
            "device_code": "SOIL_01",
            "metrics": {},
        }
        with pytest.raises(Exception):
            MQTTIngestionClient._normalize(raw)
