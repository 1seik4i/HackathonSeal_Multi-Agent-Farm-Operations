from __future__ import annotations

import json
import logging

import paho.mqtt.client as mqtt

from src.data_processor import IoTDataProcessor
from src.models import TelemetryMessage
from src.settings import settings
from src.storage import FarmStore

log = logging.getLogger(__name__)


class MQTTIngestionClient:
    """Subscribes to the contest topic and stores validated telemetry only."""

    def __init__(self, store: FarmStore, mongo_store=None) -> None:
        self.store = store
        self.mongo_store = mongo_store
        self.processor = IoTDataProcessor(stale_after_seconds=settings.stale_after_seconds)
        transport_protocol = "websockets" if settings.mqtt_port == 443 else "tcp"
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="farmops-team-2", transport=transport_protocol)
        
        if transport_protocol == "websockets":
            self.client.ws_set_options(path="/mqtt")
            
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        if settings.mqtt_username:
            self.client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        if settings.mqtt_tls:
            self.client.tls_set()

    @staticmethod
    def _normalize(payload: dict) -> list[TelemetryMessage]:
        if "devices" in payload and isinstance(payload["devices"], list):
            base_timestamp = payload.get("timestamp")
            messages = []
            for device in payload["devices"]:
                flat_payload = {
                    "device_code": device.get("deviceCode", device.get("device_id", "")),
                    "timestamp": device.get("timestamp", base_timestamp),
                    "metrics": device.get("metrics", {})
                }
                messages.append(MQTTIngestionClient._normalize_single(flat_payload))
            return messages
        else:
            return [MQTTIngestionClient._normalize_single(payload)]

    @staticmethod
    def _normalize_single(payload: dict) -> TelemetryMessage:
        metrics = payload.get("metrics")
        if metrics is None:
            metrics = {key: value for key, value in payload.items() if key not in {"device_code", "device_id", "timestamp", "device", "ts"}}
        
        device_code = payload.get("device_id", payload.get("device_code", payload.get("device")))
        normalized = {
            "device_code": device_code,
            "metrics": metrics,
        }
        
        timestamp = payload.get("timestamp", payload.get("ts"))
        if timestamp is not None:
            if isinstance(timestamp, str):
                try:
                    from datetime import datetime
                    ts_str = timestamp.replace("Z", "+00:00")
                    timestamp = datetime.fromisoformat(ts_str).timestamp()
                except ValueError as error:
                    log.warning("Failed to parse ISO-8601 timestamp '%s': %s", timestamp, error)
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
            normalized_list = self._normalize(payload)

            for normalized in normalized_list:
                # 1. Keep SQLite path for TV2/TV3 compatibility
                self.store.ingest(normalized)

                # 2. Run data processing pipeline → MongoDB
                try:
                    processed = self.processor.process(normalized.model_dump())
                    if self.mongo_store is not None:
                        self.mongo_store.ingest(processed)
                        log.info("telemetry processed & stored in MongoDB for %s", normalized.device_code)
                except ValueError as proc_err:
                    log.warning("data processing failed for %s: %s", normalized.device_code, proc_err)

                log.info("telemetry accepted from %s", normalized.device_code)
        except Exception as error:
            log.warning("telemetry rejected: %s", error)

    def start(self) -> bool:
        if not settings.mqtt_host or not settings.mqtt_password:
            log.warning("MQTT is not configured; use the demo ingestion API until .env has complete credentials")
            return False
        self.client.connect_async(settings.mqtt_host, settings.mqtt_port, keepalive=60)
        self.client.loop_start()
        return True
