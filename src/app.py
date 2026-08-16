from __future__ import annotations

from typing import Literal

import logging
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from src.agents import FarmCoordinatorAgent
from src.models import ManagerRequest, TelemetryMessage
from src.mongo_storage import MongoTelemetryStore
from src.mqtt_client import MQTTIngestionClient
from src.settings import settings
from src.storage import FarmStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
store = FarmStore(settings.database_path)
mongo_store = MongoTelemetryStore(settings.mongodb_uri, settings.mongodb_db_name) if settings.mongodb_uri else None
coordinator = FarmCoordinatorAgent(store, mongo_store=mongo_store)
mqtt_ingestion = MQTTIngestionClient(store, mongo_store=mongo_store)
app = FastAPI(title="FarmOps AI — Team 2", version="1.0.0")


@app.on_event("startup")
def start_mqtt() -> None:
    mqtt_ingestion.start()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "mqtt_configured": bool(settings.mqtt_host and settings.mqtt_password), "topic": settings.mqtt_topic}


@app.post("/api/telemetry")
def demo_ingest(message: TelemetryMessage) -> dict:
    """Demo endpoint; contest messages normally enter through MQTT.
    Data posted here is also passed through TV1's pipeline and MongoDB.
    """
    # 1. Keep SQLite path
    store.ingest(message)
    
    # 2. Run TV1 data processing pipeline -> MongoDB
    try:
        processed = mqtt_ingestion.processor.process(message.model_dump())
        if mongo_store is not None:
            mongo_store.ingest(processed)
    except ValueError as err:
        logging.warning("API ingestion processing failed: %s", err)

    return {"accepted": True, "device_code": message.device_code}


@app.post("/api/demo/seed")
def seed_demo_data() -> dict:
    DeviceCode = Literal["PH_01", "PUMP_01", "SOIL_01", "SUN_01", "TANK_01", "WEATHER_01"]
    samples: list[tuple[DeviceCode, dict[str, float]]] = [
        ("SOIL_01", {"soil_moisture": 27, "temperature": 31.2}),
        ("WEATHER_01", {"temperature": 35, "humidity": 48}),
        ("PUMP_01", {"flow_rate": 18, "power": 430}),
        ("PH_01", {"ph": 6.4}),
        ("TANK_01", {"level": 62}),
        ("SUN_01", {"lux": 78000}),
    ]
    for device_code, metrics in samples:
        store.ingest(TelemetryMessage(device_code=device_code, timestamp=time.time(), metrics=metrics))
    return {"accepted": len(samples), "mode": "demo"}


@app.get("/api/telemetry/latest")
def latest_telemetry() -> dict:
    return store.latest_by_device()


@app.post("/api/coordinate")
def coordinate(request: ManagerRequest) -> dict:
    return coordinator.handle(request.request, request.manager_name)


@app.post("/api/dialogue/summary")
def dialogue_summary(request: ManagerRequest) -> dict:
    """API mới: Trả về kết quả cuộc đối thoại trò chuyện AI ngắn gọn 2-3 dòng cho giao diện Frontend."""
    result = coordinator.handle(request.request, request.manager_name)
    narrative = coordinator.summarize_dialogue(result)
    action_info = result.get("agent_trace", [{}, {}, {}, {}])[3]
    return {
        "status": "success",
        "manager_request": request.request,
        "manager_name": request.manager_name,
        "narrative_summary": narrative,
        "action_type": action_info.get("created", {}).get("action_type"),
        "verification_status": action_info.get("verification", {}).get("status"),
        "agent_dialogue": result.get("agent_dialogue", [])
    }


@app.get("/api/dialogue/summary")
def dialogue_summary_get() -> dict:
    """GET Endpoint tiện lợi cho việc xem trực tiếp trên trình duyệt."""
    req = ManagerRequest(request="Hãy kiểm tra và lập kế hoạch tưới hôm nay", manager_name="Quản lý Trang trại A")
    return dialogue_summary(req)



@app.get("/api/actions/{action_id}")
def get_action(action_id: str) -> dict:
    action = store.get_action(action_id)
    if action is None:
        raise HTTPException(404, "Action not found")
    return action.model_dump()


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    uvicorn.run("src.app:app", host=settings.api_host, port=settings.api_port, reload=True)
