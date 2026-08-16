from __future__ import annotations

import json
import logging

import paho.mqtt.client as mqtt

from src.models import TelemetryMessage
from src.settings import settings
from src.storage import FarmStore


log = logging.getLogger(__name__)


class MQTTIngestionClient:
    """Subscribes to the contest topic and stores validated telemetry only."""

    def __init__(self, store: FarmStore) -> None:
        self.store = store
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="farmops-team-2")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        if settings.mqtt_username:
            self.client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        if settings.mqtt_tls:
            self.client.tls_set()

    @staticmethod
    def _normalize(payload: dict) -> TelemetryMessage:
        metrics = payload.get("metrics")
        if metrics is None:
            metrics = {key: value for key, value in payload.items() if key not in {"device_code", "timestamp", "device", "ts"}}
        normalized = {
            "device_code": payload.get("device_code", payload.get("device")),
            "metrics": metrics,
        }
        timestamp = payload.get("timestamp", payload.get("ts"))
        if timestamp is not None:
            normalized["timestamp"] = timestamp
        return TelemetryMessage.model_validate(normalized)

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            log.error("MQTT connection failed: %s", reason_code)
            return
        client.subscribe(settings.mqtt_topic, qos=1)
        log.info("MQTT connected; subscribed to configured telemetry topic")

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties) -> None:
        log.warning("MQTT disconnected: %s", reason_code)

    def _on_message(self, client, userdata, message) -> None:
        try:
            payload = json.loads(message.payload.decode("utf-8"))
            self.store.ingest(self._normalize(payload))
            log.info("telemetry accepted from %s", payload.get("device_code", payload.get("device")))
        except Exception as error:
            log.warning("telemetry rejected: %s", error)

    def start(self) -> bool:
        if not settings.mqtt_host or not settings.mqtt_password:
            log.warning("MQTT is not configured; use the demo ingestion API until .env has complete credentials")
            return False
        self.client.connect_async(settings.mqtt_host, settings.mqtt_port, keepalive=60)
        self.client.loop_start()
        return True
