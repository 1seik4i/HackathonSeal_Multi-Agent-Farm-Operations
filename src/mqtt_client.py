"""Backward-compatible import for the production MQTT service."""

from src.mqtt_service import MQTTIngestionClient

__all__ = ["MQTTIngestionClient"]
