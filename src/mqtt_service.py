from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime
from typing import Any

import paho.mqtt.client as mqtt
from pydantic import ValidationError

from src.data_processor import IoTDataProcessor
from src.models import TelemetryMessage
from src.settings import settings
from src.storage import FarmStore


log = logging.getLogger(__name__)


class MQTTIngestionClient:
    """Secure MQTT subscriber that normalizes and persists contest telemetry."""

    def __init__(self, store: FarmStore, mongo_store: Any = None) -> None:
        self.store = store
        self.mongo_store = mongo_store
        self.processor = IoTDataProcessor(settings.stale_after_seconds)
        self.connected = False
        self.subscribed = False
        self.started = False
        self.last_error: str | None = None
        self.last_connected_at: float | None = None
        self.last_disconnected_at: float | None = None
        self.last_message_at: float | None = None
        self.last_subscription_at: float | None = None
        self.messages_received = 0
        self.records_accepted = 0
        self.records_rejected = 0
        self.reconnect_count = 0
        self._ever_connected = False
        self._lock = threading.Lock()
        self.client = self._build_client()

    def _build_client(self) -> mqtt.Client:
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"{settings.mqtt_client_id_prefix}-{uuid.uuid4().hex[:8]}",
            protocol=mqtt.MQTTv311,
            transport=settings.mqtt_transport,
        )
        client.enable_logger(log)
        client.on_connect = self._on_connect
        client.on_connect_fail = self._on_connect_fail
        client.on_subscribe = self._on_subscribe
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        if settings.mqtt_username:
            client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        if settings.mqtt_tls:
            client.tls_set()
        if settings.mqtt_transport == "websockets":
            client.ws_set_options(path=settings.mqtt_websocket_path)
        return client

    @staticmethod
    def _timestamp(value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                try:
                    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    return None
        return None

    @classmethod
    def _normalize_one(cls, payload: dict[str, Any], root: dict[str, Any] | None = None) -> TelemetryMessage:
        root = root or payload
        device_code = payload.get("device_code", payload.get("deviceCode", payload.get("device_id", payload.get("device"))))
        metrics = payload.get("metrics")
        if metrics is None:
            ignored = {"device_code", "deviceCode", "device_id", "device", "timestamp", "ts", "epoch", "status"}
            metrics = {key: value for key, value in payload.items() if key not in ignored}
        if not isinstance(metrics, dict):
            raise ValueError("metrics must be an object")
        metrics = dict(metrics)
        if device_code == "PUMP_01" and "pump_status" not in metrics and payload.get("status") is not None:
            metrics["pump_status"] = 1.0 if str(payload["status"]).lower() in {"ok", "online", "ready", "running"} else 0.0
        timestamp = cls._timestamp(payload.get("epoch", payload.get("timestamp", payload.get("ts"))))
        if timestamp is None:
            timestamp = cls._timestamp(root.get("epoch", root.get("timestamp", root.get("ts"))))
        normalized: dict[str, Any] = {"device_code": device_code, "metrics": metrics}
        if timestamp is not None:
            normalized["timestamp"] = timestamp
        return TelemetryMessage.model_validate(normalized)

    @classmethod
    def _normalize(cls, payload: dict[str, Any]) -> TelemetryMessage:
        """Backward-compatible single-device parser used by earlier branch tests."""
        return cls._normalize_one(payload)

    @classmethod
    def normalize_payload(cls, payload: dict[str, Any]) -> tuple[list[TelemetryMessage], int]:
        """Supports both the live six-device batch and legacy single-device payloads."""
        candidates = payload.get("devices")
        if candidates is None:
            candidates = [payload]
        if not isinstance(candidates, list):
            raise ValueError("devices must be an array")
        messages: list[TelemetryMessage] = []
        rejected = 0
        for candidate in candidates:
            if not isinstance(candidate, dict):
                rejected += 1
                continue
            try:
                messages.append(cls._normalize_one(candidate, payload))
            except (ValidationError, TypeError, ValueError) as error:
                rejected += 1
                log.warning("MQTT device record rejected: %s", error)
        return messages, rejected

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            with self._lock:
                self.connected = False
                self.subscribed = False
                self.last_error = f"connection rejected: {reason_code}"
            log.error("MQTT connection rejected: %s", reason_code)
            return
        with self._lock:
            if self._ever_connected:
                self.reconnect_count += 1
            self._ever_connected = True
            self.connected = True
            self.subscribed = False
            self.last_connected_at = time.time()
            self.last_error = None
        result, _ = client.subscribe(settings.mqtt_topic, qos=1)
        if result != mqtt.MQTT_ERR_SUCCESS:
            with self._lock:
                self.last_error = f"subscribe request failed: {mqtt.error_string(result)}"
            log.error("MQTT subscribe request failed: %s", mqtt.error_string(result))
        else:
            log.info("MQTT connected over %s; subscription requested", settings.mqtt_transport)

    def _on_connect_fail(self, client, userdata) -> None:
        with self._lock:
            self.connected = False
            self.subscribed = False
            self.last_error = "network connection failed"
        log.warning("MQTT network connection failed; automatic retry is active")

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties) -> None:
        failed = any(code.is_failure for code in reason_codes)
        with self._lock:
            self.subscribed = not failed
            self.last_subscription_at = time.time() if not failed else None
            self.last_error = f"subscription rejected: {reason_codes}" if failed else None
        if failed:
            log.error("MQTT subscription rejected: %s", reason_codes)
        else:
            log.info("MQTT subscription active on configured telemetry topic")

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties) -> None:
        with self._lock:
            self.connected = False
            self.subscribed = False
            self.last_disconnected_at = time.time()
            if reason_code.is_failure:
                self.last_error = f"unexpected disconnect: {reason_code}"
        if reason_code.is_failure:
            log.warning("MQTT disconnected unexpectedly: %s", reason_code)
        else:
            log.info("MQTT client disconnected")

    def _on_message(self, client, userdata, message) -> None:
        try:
            raw_payload = message.payload.decode("utf-8")
            payload = json.loads(raw_payload)
            if not isinstance(payload, dict):
                raise ValueError("root payload must be an object")
            messages, rejected = self.normalize_payload(payload)
            accepted = 0
            for telemetry in messages:
                try:
                    processed = self.processor.process(telemetry.model_dump())
                    self.store.ingest(
                        telemetry,
                        source_type="MQTT",
                        topic=message.topic,
                        raw_payload=raw_payload,
                        quality=processed["quality"],
                    )
                    if self.mongo_store is not None:
                        try:
                            self.mongo_store.ingest(processed)
                        except Exception as mongo_err:
                            log.warning("MongoDB ingestion failed: %s", mongo_err)
                    accepted += 1
                except Exception as error:
                    rejected += 1
                    log.warning("MQTT persistence failed for %s: %s", telemetry.device_code, error)
            with self._lock:
                self.messages_received += 1
                self.records_accepted += accepted
                self.records_rejected += rejected
                self.last_message_at = time.time()
                if accepted:
                    self.last_error = None
            log.info("MQTT batch processed: accepted=%s rejected=%s", accepted, rejected)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            with self._lock:
                self.messages_received += 1
                self.records_rejected += 1
                self.last_message_at = time.time()
                self.last_error = f"payload rejected: {type(error).__name__}"
            log.warning("MQTT payload rejected: %s", error)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "configured": settings.mqtt_is_configured,
                "connected": self.connected,
                "subscribed": self.subscribed,
                "transport": settings.mqtt_transport,
                "tls": settings.mqtt_tls,
                "host": settings.mqtt_host,
                "port": settings.mqtt_port,
                "topic": settings.mqtt_topic,
                "last_connected_at": self.last_connected_at,
                "last_disconnected_at": self.last_disconnected_at,
                "last_subscription_at": self.last_subscription_at,
                "last_message_at": self.last_message_at,
                "messages_received": self.messages_received,
                "records_accepted": self.records_accepted,
                "records_rejected": self.records_rejected,
                "reconnect_count": self.reconnect_count,
                "last_error": self.last_error,
            }

    def start(self) -> bool:
        if not settings.mqtt_is_configured:
            self.last_error = "MQTT configuration is incomplete or invalid"
            log.warning("MQTT startup skipped because configuration is incomplete")
            return False
        if self.started:
            return True
        self.started = True
        self.client.connect_async(settings.mqtt_host, settings.mqtt_port, keepalive=settings.mqtt_keepalive_seconds)
        self.client.loop_start()
        return True

    def stop(self) -> None:
        if not self.started:
            return
        self.started = False
        self.client.disconnect()
        self.client.loop_stop()

    def restart(self) -> bool:
        self.stop()
        self.client = self._build_client()
        return self.start()
