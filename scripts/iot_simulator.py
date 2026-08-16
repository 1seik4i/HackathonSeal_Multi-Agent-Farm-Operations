#!/usr/bin/env python
"""IoT Sensor Simulator for FarmOps AI.

TV1 — IoT & Data Engineer
Publishes simulated telemetry to the MQTT broker (or HTTP API) so the
whole team can test without real hardware.

Usage:
    python scripts/iot_simulator.py --mode normal      # 6 healthy sensors
    python scripts/iot_simulator.py --mode stale        # timestamps 10 min old
    python scripts/iot_simulator.py --mode low-resource # tank low, pump bad
    python scripts/iot_simulator.py --mode mixed        # cycles through all
    python scripts/iot_simulator.py --mode http         # POST to /api/telemetry
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("iot-simulator")

# ---------------------------------------------------------------------------
# Sensor payload generators
# ---------------------------------------------------------------------------

def _ts_iso(offset_seconds: float = 0) -> str:
    """ISO-8601 UTC timestamp with optional backwards offset."""
    return datetime.fromtimestamp(
        time.time() - offset_seconds, tz=timezone.utc
    ).isoformat()


def normal_payloads() -> list[dict]:
    """Healthy data from all 6 sensors."""
    return [
        {
            "device_id": "SOIL_01",
            "timestamp": _ts_iso(),
            "metrics": {
                "soil_moisture": round(random.uniform(20, 45), 1),
                "temperature": round(random.uniform(25, 35), 1),
            },
        },
        {
            "device_id": "WEATHER_01",
            "timestamp": _ts_iso(),
            "metrics": {
                "temperature": round(random.uniform(28, 38), 1),
                "humidity": round(random.uniform(40, 70), 1),
            },
        },
        {
            "device_id": "PUMP_01",
            "timestamp": _ts_iso(),
            "metrics": {
                "flow_rate": round(random.uniform(12, 25), 1),
                "power": round(random.uniform(350, 500), 0),
            },
        },
        {
            "device_id": "PH_01",
            "timestamp": _ts_iso(),
            "metrics": {"ph": round(random.uniform(6.0, 7.2), 1)},
        },
        {
            "device_id": "TANK_01",
            "timestamp": _ts_iso(),
            "metrics": {"level": round(random.uniform(50, 90), 0)},
        },
        {
            "device_id": "SUN_01",
            "timestamp": _ts_iso(),
            "metrics": {"lux": round(random.uniform(30000, 90000), 0)},
        },
    ]


def stale_payloads() -> list[dict]:
    """Data with timestamps 10 minutes in the past → triggers STALE."""
    stale_offset = 600  # 10 minutes
    return [
        {
            "device_id": "SOIL_01",
            "timestamp": _ts_iso(stale_offset),
            "metrics": {
                "soil_moisture": round(random.uniform(20, 45), 1),
                "temperature": round(random.uniform(25, 35), 1),
            },
        },
        {
            "device_id": "WEATHER_01",
            "timestamp": _ts_iso(stale_offset),
            "metrics": {
                "temperature": round(random.uniform(28, 38), 1),
                "humidity": round(random.uniform(40, 70), 1),
            },
        },
    ]


def low_resource_payloads() -> list[dict]:
    """Tank nearly empty + pump anomaly → Resource Agent blocks irrigation."""
    return [
        {
            "device_id": "SOIL_01",
            "timestamp": _ts_iso(),
            "metrics": {
                "soil_moisture": round(random.uniform(10, 25), 1),
                "temperature": round(random.uniform(30, 40), 1),
            },
        },
        {
            "device_id": "TANK_01",
            "timestamp": _ts_iso(),
            "metrics": {"level": round(random.uniform(5, 15), 0)},
        },
        {
            "device_id": "PUMP_01",
            "timestamp": _ts_iso(),
            "metrics": {"flow_rate": 0, "power": 0},
        },
    ]


# ---------------------------------------------------------------------------
# Publishers
# ---------------------------------------------------------------------------

def publish_mqtt(payloads: list[dict], topic: str, host: str, port: int,
                 username: str, password: str, use_tls: bool) -> None:
    """Publish payloads to the MQTT broker."""
    # pyrefly: ignore [missing-import]
    import paho.mqtt.client as mqtt_lib

    client = mqtt_lib.Client(mqtt_lib.CallbackAPIVersion.VERSION2, client_id="farmops-simulator")
    if username:
        client.username_pw_set(username, password)
    if use_tls:
        client.tls_set()

    client.connect(host, port, keepalive=60)
    client.loop_start()
    time.sleep(1)  # wait for connection

    for payload in payloads:
        msg = json.dumps(payload)
        info = client.publish(topic, msg, qos=1)
        info.wait_for_publish(timeout=5)
        log.info("MQTT published → %s  %s", payload["device_id"], msg[:80])

    client.loop_stop()
    client.disconnect()


def publish_http(payloads: list[dict], api_url: str) -> None:
    """POST payloads to the REST telemetry endpoint."""
    import urllib.request

    for payload in payloads:
        # Convert ISO timestamp to float for the HTTP API
        from datetime import datetime as dt
        ts = payload.get("timestamp")
        if isinstance(ts, str):
            ts = dt.fromisoformat(ts.replace("Z", "+00:00")).timestamp()

        body = {
            "device_code": payload.get("device_id", payload.get("device_code")),
            "timestamp": ts,
            "metrics": payload["metrics"],
        }
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            api_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                log.info("HTTP %s → %s  %s", resp.status, body["device_code"], resp.read().decode())
        except Exception as err:  # noqa: BLE001
            log.error("HTTP POST failed for %s: %s", body["device_code"], err)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="FarmOps IoT Simulator")
    parser.add_argument(
        "--mode",
        choices=["normal", "stale", "low-resource", "mixed", "http"],
        default="normal",
        help="Simulation mode (default: normal)",
    )
    parser.add_argument("--host", default="", help="MQTT broker host (reads .env if empty)")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--topic", default="hackathon/team_2/test/telemetry")
    parser.add_argument("--username", default="TEAM_2")
    parser.add_argument("--password", default="", help="MQTT password")
    parser.add_argument("--tls", action="store_true")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000/api/telemetry", help="HTTP API URL for http mode")
    parser.add_argument("--interval", type=float, default=5.0, help="Seconds between publishes")
    parser.add_argument("--count", type=int, default=0, help="Number of rounds (0 = infinite)")
    args = parser.parse_args()

    # Try to load .env values
    try:
        import os

        from dotenv import load_dotenv
        load_dotenv()
        if not args.host:
            args.host = os.getenv("MQTT_BROKER_HOST", "")
        if not args.password:
            args.password = os.getenv("MQTT_PASSWORD", os.getenv("PASSWORD", ""))
    except ImportError:
        pass

    modes = {
        "normal": normal_payloads,
        "stale": stale_payloads,
        "low-resource": low_resource_payloads,
    }

    if args.mode == "http":
        log.info("HTTP mode — sending to %s", args.api_url)
        payloads = normal_payloads()
        publish_http(payloads, args.api_url)
        return

    if args.mode == "mixed":
        cycle = ["normal", "stale", "low-resource"]
    else:
        cycle = [args.mode]

    if not args.host:
        log.error("No MQTT broker host. Set MQTT_BROKER_HOST in .env or use --host. "
                  "Try --mode http to use the REST API instead.")
        sys.exit(1)

    log.info("Starting simulator — mode=%s, host=%s, topic=%s", args.mode, args.host, args.topic)
    round_num = 0
    try:
        while True:
            current_mode = cycle[round_num % len(cycle)]
            payloads = modes[current_mode]()
            log.info("=== Round %d — mode: %s ===", round_num + 1, current_mode)
            publish_mqtt(
                payloads, args.topic, args.host, args.port,
                args.username, args.password, args.tls,
            )
            round_num += 1
            if 0 < args.count <= round_num:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        log.info("Simulator stopped by user after %d rounds", round_num)


if __name__ == "__main__":
    main()
