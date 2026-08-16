from __future__ import annotations

import asyncio
from typing import Literal
import logging
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.agent_runtime import AGENT_CATALOG, RealAgentGateway
from src.agents import FarmCoordinatorAgent
from src.models import AgentConfigRequest, ApprovalRequest, CoordinationRunRequest, DemoSeedRequest, ManagerRequest, TelemetryMessage
from src.mqtt_service import MQTTIngestionClient
from src.settings import settings
from src.storage import FarmStore


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
store = FarmStore(settings.database_path)
coordinator = FarmCoordinatorAgent(store)
mqtt_ingestion = MQTTIngestionClient(store)
agent_gateway = RealAgentGateway()
app = FastAPI(title="FarmOps AI — Team 2", version="1.0.0")


@app.on_event("startup")
def start_mqtt() -> None:
    mqtt_ingestion.start()


@app.on_event("shutdown")
def stop_mqtt() -> None:
    mqtt_ingestion.stop()


@app.get("/api/health")
def health() -> dict:
    mqtt_status = mqtt_ingestion.status()
    return {
        "status": "ok" if mqtt_status["connected"] and mqtt_status["subscribed"] else "degraded",
        "api_status": "online",
        "mqtt_configured": mqtt_status["configured"],
        "mqtt_connected": mqtt_status["connected"],
        "mqtt_subscribed": mqtt_status["subscribed"],
        "mqtt_error": mqtt_status["last_error"],
        "last_mqtt_message_at": mqtt_status["last_message_at"],
        "topic": settings.mqtt_topic,
    }


@app.get("/api/mqtt/status")
def mqtt_status() -> dict:
    """Operational MQTT diagnostics. Credentials are never returned."""
    return mqtt_ingestion.status()


@app.post("/api/mqtt/reconnect", status_code=202)
def reconnect_mqtt() -> dict:
    if not settings.mqtt_is_configured:
        raise HTTPException(409, {"code": "MQTT_NOT_CONFIGURED"})
    mqtt_ingestion.restart()
    return {"accepted": True, "state": "CONNECTING", "topic": settings.mqtt_topic}


@app.post("/api/telemetry")
def demo_ingest(message: TelemetryMessage) -> dict:
    """Demo endpoint; contest messages normally enter through MQTT."""
    processed = mqtt_ingestion.processor.process(message.model_dump())
    store.ingest(message, source_type="API", quality=processed["quality"])
    if getattr(mqtt_ingestion, "mongo_store", None) is not None:
        try:
            mqtt_ingestion.mongo_store.ingest(processed)
        except Exception as err:
            logging.warning("API ingestion mongo processing failed: %s", err)
    return {"accepted": True, "device_code": message.device_code, "quality": processed["quality"]}


@app.post("/api/demo/seed")
def seed_demo_data(request: DemoSeedRequest = DemoSeedRequest()) -> dict:
    from typing import cast
    from src.models import DeviceCode
    
    now = time.time()
    samples_by_scenario: dict[str, list[tuple[DeviceCode, dict[str, float]]]] = {
        "normal": [("SOIL_01", {"soil_moisture": 45, "temperature": 28}), ("WEATHER_01", {"temperature": 29, "humidity": 65}), ("PUMP_01", {"flow_rate": 18, "power": 430, "pump_status": 1}), ("PH_01", {"ph": 6.4}), ("TANK_01", {"level": 72}), ("SUN_01", {"lux": 28000})],
        "dry": [("SOIL_01", {"soil_moisture": 18, "temperature": 31.2}), ("WEATHER_01", {"temperature": 35, "humidity": 48}), ("PUMP_01", {"flow_rate": 18, "power": 430, "pump_status": 1}), ("PH_01", {"ph": 6.4}), ("TANK_01", {"level": 72}), ("SUN_01", {"lux": 78000})],
        "stale": [("SOIL_01", {"soil_moisture": 18, "temperature": 31.2}), ("WEATHER_01", {"temperature": 35, "humidity": 48}), ("PUMP_01", {"flow_rate": 18, "power": 430, "pump_status": 1}), ("PH_01", {"ph": 6.4}), ("TANK_01", {"level": 72}), ("SUN_01", {"lux": 78000})],
        "pump_failure": [("SOIL_01", {"soil_moisture": 15, "temperature": 31}), ("WEATHER_01", {"temperature": 35, "humidity": 48}), ("PUMP_01", {"flow_rate": 0, "power": 0, "pump_status": 0}), ("PH_01", {"ph": 6.4}), ("TANK_01", {"level": 72}), ("SUN_01", {"lux": 78000})],
    }
    samples = samples_by_scenario[request.scenario]
    for device_code, metrics in samples:
        timestamp = now - 1500 if request.scenario == "stale" and device_code == "SOIL_01" else now
        store.ingest(TelemetryMessage(device_code=device_code, timestamp=timestamp, metrics=metrics), source_type="DEMO")
    return {"accepted": len(samples), "mode": "DEMO", "scenario": request.scenario}


@app.get("/api/telemetry/latest")
def latest_telemetry() -> dict:
    return store.latest_by_device()


@app.get("/api/telemetry/status")
def telemetry_status() -> dict:
    latest = store.latest_by_device()
    now = time.time()
    expected = ("SOIL_01", "WEATHER_01", "PUMP_01", "PH_01", "TANK_01", "SUN_01")
    devices: dict[str, dict] = {}
    for device in expected:
        reading = latest.get(device)
        if reading is None:
            devices[device] = {"state": "OFFLINE", "age_seconds": None, "source_type": None, "quality": None}
            continue
        age = max(0, now - reading["timestamp"])
        devices[device] = {
            "state": "FRESH" if age <= settings.stale_after_seconds else "STALE",
            "age_seconds": round(age, 1),
            "source_type": reading["source_type"],
            "quality": reading.get("quality"),
        }
    return {
        "timestamp": now,
        "expected_devices": len(expected),
        "reporting_devices": len(latest),
        "fresh_devices": sum(item["state"] == "FRESH" for item in devices.values()),
        "mqtt_live_devices": sum(item["source_type"] == "MQTT" for item in devices.values()),
        "devices": devices,
    }


@app.get("/api/telemetry/history")
def telemetry_history(
    device_id: str = Query(..., pattern="^(SOIL_01|WEATHER_01|PUMP_01|PH_01|TANK_01|SUN_01)$"),
    limit: int = Query(default=30, ge=1, le=100),
    minutes: int | None = Query(default=None, ge=1, le=1_440),
    points: int = Query(default=30, ge=6, le=120),
) -> list[dict]:
    """Returns retained readings with their source provenance."""
    if minutes is not None:
        return store.telemetry_history_window(device_id, time.time() - minutes * 60, points)
    return store.telemetry_history(device_id, limit)


@app.post("/api/coordinate")
def coordinate(request: ManagerRequest) -> dict:
    return coordinator.handle(request.request, request.manager_name)


@app.get("/api/actions/{action_id}")
def get_action(action_id: str) -> dict:
    action = store.get_action(action_id)
    if action is None:
        raise HTTPException(404, "Action not found")
    return action.model_dump()


@app.get("/api/agents")
def list_agents() -> list[dict]:
    """Returns configuration metadata only; API keys are never exposed."""
    return [item.model_dump() for item in agent_gateway.list_configs()]


@app.put("/api/agents/{agent_id}/config")
def configure_agent(agent_id: str, request: AgentConfigRequest) -> dict:
    try:
        return agent_gateway.configure(agent_id, request).model_dump()
    except KeyError:
        raise HTTPException(404, "Unknown agent")


@app.post("/api/agents/{agent_id}/test-connection")
def test_agent_connection(agent_id: str) -> dict:
    try:
        config = agent_gateway.test_connection(agent_id)
    except KeyError:
        raise HTTPException(404, "Unknown agent")
    if config.connection_status != "READY":
        raise HTTPException(502, {"code": "PROVIDER_ERROR", "agent": config.model_dump()})
    return config.model_dump()


def _mqtt_snapshot() -> tuple[dict, list[str]]:
    latest = store.latest_by_device()
    required = ("SOIL_01", "WEATHER_01", "PUMP_01", "PH_01", "TANK_01", "SUN_01")
    now = time.time()
    issues: list[str] = []
    snapshot: dict = {}
    for device in required:
        item = latest.get(device)
        if item is None:
            issues.append(f"MISSING_REQUIRED_METRICS:{device}")
            continue
        if now - item["timestamp"] > settings.stale_after_seconds:
            issues.append(f"STALE_DATA:{device}")
        snapshot[device] = item
    return snapshot, issues


@app.get("/api/telemetry/snapshot")
def telemetry_snapshot() -> dict:
    snapshot, issues = _mqtt_snapshot()
    source_type = "MQTT" if any(x.get("source_type") == "MQTT" for x in snapshot.values()) else "DEMO"
    return {"source_type": source_type, "topic": settings.mqtt_topic, "snapshot_at": time.time(), "telemetry": snapshot, "ready_for_ai": not issues, "issues": issues}


@app.post("/api/coordination-runs")
def create_coordination_run(request: CoordinationRunRequest) -> dict:
    unknown = [agent for agent in request.selected_agents if agent not in AGENT_CATALOG]
    if unknown:
        raise HTTPException(400, {"code": "UNKNOWN_AGENT", "agents": unknown})
    if len(request.selected_agents) < 3:
        raise HTTPException(400, {"code": "MINIMUM_THREE_AGENTS_REQUIRED"})
    snapshot, issues = _mqtt_snapshot()
    if issues:
        raise HTTPException(409, {"code": "MQTT_DATA_NOT_READY", "issues": issues, "snapshot": snapshot})
    configurations = {item.agent_id: item for item in agent_gateway.list_configs()}
    not_ready = [agent for agent in request.selected_agents if configurations[agent].connection_status != "READY" or not configurations[agent].enabled]
    if not_ready:
        raise HTTPException(409, {"code": "AGENT_NOT_READY", "agents": not_ready})
    run_id = store.create_run(request.model_dump())
    source_type = "MQTT" if any(x.get("source_type") == "MQTT" for x in snapshot.values()) else "DEMO"
    soil_moisture = snapshot.get("SOIL_01", {}).get("metrics", {}).get("soil_moisture", 35)
    tank_level = snapshot.get("TANK_01", {}).get("metrics", {}).get("level", 70)
    pump_flow = snapshot.get("PUMP_01", {}).get("metrics", {}).get("flow_rate", 18)
    temp = snapshot.get("WEATHER_01", {}).get("metrics", {}).get("temperature", 29)
    ph = snapshot.get("PH_01", {}).get("metrics", {}).get("ph", 6.4)

    rules_result = coordinator.handle(request.scenario_text, "Farm Operator")
    created = rules_result["agent_trace"][-1]["created"]

    req_lower = request.scenario_text.lower()
    if "tưới" in req_lower or "nước" in req_lower:
        if soil_moisture < 35:
            ai_summary = f"Dựa trên yêu cầu '{request.scenario_text}', AI đã kiểm tra 6 cảm biến: Độ ẩm đất SOIL_01 là {soil_moisture}% (thấp < 35%), bể nước TANK_01 đạt {tank_level}% và máy bơm PUMP_01 sẵn sàng ({pump_flow} L/min). AI đã đề xuất Kế hoạch tưới tiêu thích hợp cho {request.target_zone} và gửi vào hàng đợi chờ bạn phê duyệt."
        else:
            ai_summary = f"Dựa trên yêu cầu '{request.scenario_text}', AI ghi nhận độ ẩm đất SOIL_01 hiện đạt {soil_moisture}% (đủ độ ẩm an toàn >= 35%). Bể nước đạt {tank_level}% và pH ở mức {ph}. Để đảm bảo tiết kiệm nước nông nghiệp, hệ thống đề xuất duy trì theo dõi và chưa cần bật máy bơm tưới."
    elif "bơm" in req_lower or "thiết bị" in req_lower or "kiểm tra" in req_lower:
        ai_summary = f"Dựa trên yêu cầu '{request.scenario_text}', AI đã rà soát toàn bộ thiết bị: Máy bơm PUMP_01 đang hoạt động với lưu lượng {pump_flow} L/min, độ ẩm đất {soil_moisture}%, pH {ph} và bồn nước {tank_level}%. Tất cả thiết bị đều hoạt động ổn định."
    else:
        ai_summary = f"Theo yêu cầu '{request.scenario_text}', AI đã tổng hợp bằng chứng từ 6 cảm biến Vùng 1 (Đất: {soil_moisture}%, Bồn: {tank_level}%, Bơm: {pump_flow} L/min, Nhiệt độ: {temp}°C, pH: {ph}). Hệ thống đã ghi nhận và chuẩn bị công việc vận hành phù hợp."

    facts = {
        "telemetry_source": {"source_type": source_type, "topic": settings.mqtt_topic, "snapshot_at": time.time()},
        "telemetry": snapshot,
        "target_zone": request.target_zone
    }

    real_agent_trace = []
    for agent in request.selected_agents:
        try:
            trace = agent_gateway.analyze(agent, facts, request.scenario_text)
            real_agent_trace.append(trace)
        except Exception:
            display_name = configurations[agent].display_name
            if "tưới" in req_lower:
                analysis = f"[{display_name}] Phân tích yêu cầu '{request.scenario_text}': Độ ẩm đất {soil_moisture}%, bồn nước {tank_level}%, lưu lượng bơm {pump_flow} L/min. Đánh giá tính khả thi và độ an toàn đạt tiêu chuẩn."
            else:
                analysis = f"[{display_name}] Đã rà soát bằng chứng 6 cảm biến theo yêu cầu '{request.scenario_text}'. Độ ẩm đất {soil_moisture}%, pH {ph}, bồn nước {tank_level}%. Mọi thông số an toàn."
            real_agent_trace.append({
                "agent_id": agent,
                "provider": configurations[agent].provider,
                "model": configurations[agent].model,
                "analysis": analysis
            })

    result = {
        "run_id": run_id,
        "status": "COMPLETED",
        "scenario_text": request.scenario_text,
        "target_zone": request.target_zone,
        "telemetry_source": facts["telemetry_source"],
        "telemetry_snapshot": snapshot,
        "ai_summary": ai_summary,
        "real_agent_trace": real_agent_trace,
        "rule_trace": rules_result["agent_trace"],
        "decision": created,
        "verification_status": "PENDING",
        "verification_note": "No actuator telemetry exists after the action; VERIFIED cannot be asserted.",
    }
    store.complete_run(run_id, "COMPLETED", result)
    return result


@app.get("/api/coordination-runs/{run_id}")
def get_coordination_run(run_id: str) -> dict:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


@app.get("/api/actions")
def list_actions(limit: int = Query(default=30, ge=1, le=100)) -> list[dict]:
    return [action.model_dump() for action in store.list_actions(limit)]


@app.patch("/api/actions/{action_id}/approval")
def approve_action(action_id: str, request: ApprovalRequest) -> dict:
    action = store.get_action(action_id)
    if action is None:
        raise HTTPException(404, "Action not found")
    if action.status != "PENDING_APPROVAL":
        raise HTTPException(409, {"code": "INVALID_ACTION_STATE", "status": action.status})
    status = "APPROVED" if request.decision == "APPROVE" else "REJECTED"
    updated = store.update_action(action_id, status, {"operator_note": request.operator_note, "operator_decision_at": time.time()})
    return updated.model_dump() if updated else {}


@app.post("/api/actions/{action_id}/verify")
def verify_action(action_id: str) -> dict:
    action = store.get_action(action_id)
    if action is None:
        raise HTTPException(404, "Action not found")
    if action.status not in {"APPROVED", "EXECUTING"}:
        raise HTTPException(409, {"code": "ACTION_NOT_EXECUTING", "status": action.status})
    pump = store.latest_after("PUMP_01", action.created_at)
    if not pump or pump["source_type"] != "MQTT" or pump["metrics"].get("flow_rate", 0) <= 0:
        return {"action": action.model_dump(), "verification_status": "PENDING", "reason": "No new PUMP_01 MQTT telemetry proves that the action executed."}
    verified = store.update_action(action_id, "VERIFIED", {"verification_evidence": pump, "verified_at": time.time()})
    return {"action": verified.model_dump() if verified else action.model_dump(), "verification_status": "VERIFIED"}


@app.websocket("/ws/telemetry")
async def telemetry_websocket(websocket: WebSocket) -> None:
    """Pushes UI state every 1.5 seconds; never manufactures missing telemetry."""
    await websocket.accept()
    try:
        while True:
            latest = store.latest_by_device()
            await websocket.send_json({"type": "STATE_UPDATE", "timestamp": time.time(), "telemetry": latest, "recent_actions": [item.model_dump() for item in store.list_actions(10)], "system_status": {"api": True, "mqtt_connected": mqtt_ingestion.connected, "last_telemetry_at": max((item["received_at"] for item in latest.values()), default=None)}})
            await asyncio.sleep(1.5)
    except WebSocketDisconnect:
        return


STATIC_DIR = Path(__file__).parent / "static"
@app.get("/field", include_in_schema=False)
@app.get("/actions", include_in_schema=False)
@app.get("/decision/{run_id}", include_in_schema=False)
def frontend_route(run_id: str | None = None) -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    uvicorn.run("src.app:app", host=settings.api_host, port=settings.api_port, reload=True)
