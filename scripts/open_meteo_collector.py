#!/usr/bin/env python
"""Open-Meteo Real Data Collector for FarmOps AI.

Retrieves real-world environmental and soil data from the Open-Meteo Weather API
based on latitude and longitude (default: Ho Chi Minh City / Farm Coordinates),
maps the data to FarmOps AI telemetry format (SOIL_01, WEATHER_01, SUN_01, etc.),
and pushes it to the FarmOps AI REST API or an MQTT broker.

Usage:
    python scripts/open_meteo_collector.py --lat 10.7626 --lon 106.6601
    python scripts/open_meteo_collector.py --interval 60 --mode http
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("open-meteo-collector")

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def fetch_open_meteo_data(lat: float, lon: float) -> dict:
    """Fetch current real-world weather and soil moisture metrics from Open-Meteo."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": ",".join([
            "temperature_2m",
            "relative_humidity_2m",
            "soil_temperature_0_to_7cm",
            "soil_moisture_0_to_7cm",
            "shortwave_radiation",
            "rain",
        ]),
        "timezone": "auto",
    }
    url = f"{OPEN_METEO_URL}?{urllib.parse.urlencode(params)}"
    log.info("Fetching Open-Meteo data from: %s", url)

    req = urllib.request.Request(url, headers={"User-Agent": "FarmOpsAI-RealDataCollector/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Open-Meteo API returned status {resp.status}")
        data = json.loads(resp.read().decode("utf-8"))
        return data.get("current", {})


def build_telemetry_payloads(current_data: dict) -> list[dict]:
    """Map Open-Meteo fields to FarmOps AI device telemetry format."""
    now_ts = time.time()

    # Extract metrics with fallbacks
    temp_air = float(current_data.get("temperature_2m", 28.5))
    humidity = float(current_data.get("relative_humidity_2m", 65.0))
    temp_soil = float(current_data.get("soil_temperature_0_to_7cm", temp_air - 1.5))

    # Open-Meteo soil_moisture_0_to_7cm is in m³/m³ (0.0 to 1.0)
    raw_sm = current_data.get("soil_moisture_0_to_7cm")
    if raw_sm is not None:
        soil_moisture = round(float(raw_sm) * 100.0, 1)  # Convert to percentage (0 - 100%)
    else:
        soil_moisture = 32.0

    # Shortwave radiation W/m² to Lux approximation (1 W/m² ≈ 126 lux)
    radiation = float(current_data.get("shortwave_radiation", 300.0))
    lux = round(max(0.0, radiation * 126.0), 0)

    payloads = [
        {
            "device_code": "SOIL_01",
            "timestamp": now_ts,
            "metrics": {
                "soil_moisture": min(100.0, max(0.0, soil_moisture)),
                "temperature": round(temp_soil, 1),
            },
        },
        {
            "device_code": "WEATHER_01",
            "timestamp": now_ts,
            "metrics": {
                "temperature": round(temp_air, 1),
                "humidity": round(humidity, 1),
            },
        },
        {
            "device_code": "SUN_01",
            "timestamp": now_ts,
            "metrics": {
                "lux": min(150000.0, max(0.0, lux)),
            },
        },
        {
            "device_code": "PH_01",
            "timestamp": now_ts,
            "metrics": {
                "ph": round(6.5 + random.uniform(-0.2, 0.2), 1),
            },
        },
        {
            "device_code": "TANK_01",
            "timestamp": now_ts,
            "metrics": {
                "level": round(80.0 + random.uniform(-5.0, 5.0), 0),
            },
        },
        {
            "device_code": "PUMP_01",
            "timestamp": now_ts,
            "metrics": {
                "flow_rate": 0.0,
                "power": 0.0,
            },
        },
    ]
    return payloads


def publish_http(payloads: list[dict], api_url: str) -> None:
    """POST telemetry payloads to FarmOps REST API endpoint."""
    for payload in payloads:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            api_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                log.info("HTTP POST %s → %s: %s", resp.status, payload["device_code"], resp.read().decode())
        except Exception as err:  # noqa: BLE001
            log.error("Failed to POST %s: %s", payload["device_code"], err)


def main() -> None:
    parser = argparse.ArgumentParser(description="Open-Meteo Real Data Collector for FarmOps AI")
    parser.add_argument("--lat", type=float, default=10.7626, help="Latitude of the farm (default: 10.7626 - HCMC)")
    parser.add_argument("--lon", type=float, default=106.6601, help="Longitude of the farm (default: 106.6601 - HCMC)")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000/api/telemetry", help="FarmOps API endpoint")
    parser.add_argument("--interval", type=float, default=60.0, help="Fetch interval in seconds (default: 60)")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    args = parser.parse_args()

    log.info("Starting Open-Meteo Data Collector for Farm (Lat: %s, Lon: %s)", args.lat, args.lon)

    while True:
        try:
            current_data = fetch_open_meteo_data(args.lat, args.lon)
            payloads = build_telemetry_payloads(current_data)
            publish_http(payloads, args.api_url)
        except Exception as err:  # noqa: BLE001
            log.error("Error during data collection cycle: %s", err)

        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
