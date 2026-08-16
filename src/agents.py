from __future__ import annotations

import logging
import time
from typing import Any

from src.models import Evidence
from src.mongo_storage import MongoTelemetryStore
from src.settings import settings
from src.storage import FarmStore

log = logging.getLogger(__name__)

ALL_DEVICES = ("SOIL_01", "WEATHER_01", "PUMP_01", "PH_01", "TANK_01", "SUN_01")


class FieldIoTAgent:
    name = "Field IoT Agent"

    def __init__(self, store: FarmStore, mongo_store: MongoTelemetryStore | None = None) -> None:
        self.store = store
        self.mongo_store = mongo_store

    def observe(self) -> dict[str, Any]:
        now = time.time()
        
        # 1. TV1 Integration: Read telemetry from MongoDB Atlas if available, fallback to SQLite
        latest = {}
        if self.mongo_store is not None:
            try:
                latest = self.mongo_store.latest_by_device()
                log.info("FieldIoTAgent: Successfully fetched latest telemetry from MongoDB Atlas (TV1).")
            except Exception as mongo_err:  # noqa: BLE001
                log.warning("FieldIoTAgent: Failed to fetch from MongoDB Atlas (%s). Falling back to SQLite.", mongo_err)
                latest = self.store.latest_by_device()
        else:
            latest = self.store.latest_by_device()
            
        evidence: list[Evidence] = []
        for device in ALL_DEVICES:
            item = latest.get(device)
            if item is None:
                evidence.append(Evidence(
                    device_code=device,
                    device_id=device,
                    metric="-",
                    value="-",
                    freshness="MISSING",
                    reason="Chưa nhận được dữ liệu MQTT.",
                    timestamp=None,
                    agent=self.name
                ))
                continue
                
            # Compute freshness based on actual timestamp
            freshness = "FRESH" if now - item["timestamp"] <= settings.stale_after_seconds else "STALE"
            for metric, value in item["metrics"].items():
                evidence.append(Evidence(
                    device_code=device,
                    device_id=device,
                    metric=metric,
                    value=value,
                    freshness=freshness,
                    reason="Dữ liệu đủ mới để lập kế hoạch." if freshness == "FRESH" else "Dữ liệu đã cũ, cần xác minh ngoài hiện trường.",
                    timestamp=item["timestamp"],
                    agent=self.name
                ))
        return {"agent": self.name, "latest": latest, "evidence": [item.model_dump() for item in evidence]}


class IrrigationPlanningAgent:
    name = "Irrigation Planning Agent"

    def plan(self, observation: dict[str, Any]) -> dict[str, Any]:
        # NOTE FOR API KEY: Retrieve the API key from settings/env if utilizing LLM reasoning:
        # api_key = os.getenv("GEMINI_API_KEY")
        
        data = observation["latest"]
        soil = data.get("SOIL_01", {}).get("metrics", {}).get("soil_moisture")
        weather = data.get("WEATHER_01", {}).get("metrics", {})
        sun = data.get("SUN_01", {}).get("metrics", {}).get("lux")
        
        stale_soil = any(x["device_code"] == "SOIL_01" and x["freshness"] == "STALE" for x in observation["evidence"])
        missing_soil = any(x["device_code"] == "SOIL_01" and x["freshness"] == "MISSING" for x in observation["evidence"])
        
        if missing_soil:
            return {"agent": self.name, "decision": "NEEDS_FIELD_CHECK", "reason": "SENSOR_DATA_MISSING", "schedule": None}
        if stale_soil:
            return {"agent": self.name, "decision": "NEEDS_FIELD_CHECK", "reason": "SENSOR_DATA_STALE", "schedule": None}
        if soil is None:
            return {"agent": self.name, "decision": "NEEDS_FIELD_CHECK", "reason": "SENSOR_DATA_MISSING", "schedule": None}
            
        temperature = weather.get("temperature", 0)
        if soil < 35:
            slot = "17:30" if sun and sun > 40_000 else "08:00"
            return {
                "agent": self.name,
                "decision": "IRRIGATE",
                "reason": f"Độ ẩm đất {soil}% thấp; nhiệt độ {temperature}°C và ánh sáng được dùng để chọn giờ tưới.",
                "schedule": {
                    "start_time": slot,
                    "duration_minutes": 20,
                    "priority": "HIGH",
                    "target_zone": "Khu A"
                }
            }
        return {"agent": self.name, "decision": "NO_IRRIGATION", "reason": f"Độ ẩm đất {soil}% chưa yêu cầu tưới.", "schedule": None}


class ResourceAgent:
    name = "Resource Agent"

    def check(self, observation: dict[str, Any], irrigation: dict[str, Any]) -> dict[str, Any]:
        data = observation["latest"]
        tank = data.get("TANK_01", {}).get("metrics", {}).get("level")
        ph = data.get("PH_01", {}).get("metrics", {}).get("ph")
        pump = data.get("PUMP_01", {}).get("metrics", {})
        
        if irrigation["decision"] != "IRRIGATE":
            return {"agent": self.name, "approved": False, "reason": "Chưa có kế hoạch tưới để cấp tài nguyên."}
            
        blockers = []
        
        # Check freshness of critical resource sensors
        missing_tank = any(x["device_code"] == "TANK_01" and x["freshness"] == "MISSING" for x in observation["evidence"])
        stale_tank = any(x["device_code"] == "TANK_01" and x["freshness"] == "STALE" for x in observation["evidence"])
        missing_pump = any(x["device_code"] == "PUMP_01" and x["freshness"] == "MISSING" for x in observation["evidence"])
        stale_pump = any(x["device_code"] == "PUMP_01" and x["freshness"] == "STALE" for x in observation["evidence"])
        
        if missing_tank or stale_tank:
            blockers.append("SENSOR_DATA_MISSING_OR_STALE (TANK_01)")
        elif tank is None or tank < 25:
            blockers.append("INSUFFICIENT_WATER")
            
        if ph is None or not 5.5 <= ph <= 7.5:
            blockers.append("PH_OUT_OF_RANGE")
            
        if missing_pump or stale_pump:
            blockers.append("SENSOR_DATA_MISSING_OR_STALE (PUMP_01)")
        else:
            flow_rate = pump.get("flow_rate", 0)
            power = pump.get("power", 0)
            # Pump abnormal check: expected is ~18 L/min. If not operating correctly or flow rate falls below threshold:
            if flow_rate <= 0 or power <= 0 or flow_rate < 10.0 or flow_rate > 25.0:
                blockers.append("PUMP_ABNORMAL")
                
        return {"agent": self.name, "approved": not blockers, "reason": "; ".join(blockers) if blockers else "Nước, pH và bơm đáp ứng điều kiện mô phỏng."}


class FarmActionAgent:
    name = "Farm Action Agent"

    def __init__(self, store: FarmStore) -> None:
        self.store = store

    def create(self, irrigation: dict[str, Any], resources: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
        expected_type = "FIELD_TASK"
        expected_zone = None
        expected_duration = None
        
        if irrigation["decision"] == "IRRIGATE" and resources["approved"]:
            expected_type = "IRRIGATION_PLAN"
            expected_zone = irrigation["schedule"]["target_zone"]
            expected_duration = irrigation["schedule"]["duration_minutes"]
            action = self.store.create_action(
                "IRRIGATION_PLAN", 
                "PENDING_APPROVAL", 
                {
                    "schedule": irrigation["schedule"], 
                    "evidence": evidence, 
                    "resource_check": resources
                }
            )
        else:
            if irrigation["decision"] == "NEEDS_FIELD_CHECK":
                reason = irrigation["reason"]
            elif not resources["approved"]:
                blockers = resources["reason"].split("; ")
                if "INSUFFICIENT_WATER" in blockers:
                    reason = "INSUFFICIENT_WATER"
                elif "PUMP_ABNORMAL" in blockers:
                    reason = "PUMP_ABNORMAL"
                else:
                    reason = blockers[0]
            else:
                reason = "NO_IRRIGATION_NEEDED"
                
            action = self.store.create_action(
                "FIELD_TASK", 
                "CREATED", 
                {
                    "task": "INSPECT_SENSOR_OR_RESOURCE", 
                    "reason": reason, 
                    "evidence": evidence
                }
            )
            
        verified = self.store.verify_action(
            action.id, 
            expected_type=expected_type, 
            expected_zone=expected_zone, 
            expected_duration=expected_duration
        )
        return {
            "agent": self.name,
            "created": action.model_dump(),
            "verification": verified.model_dump() if verified else {"status": "FAILED"}
        }


class FarmCoordinatorAgent:
    name = "Farm Coordinator Agent"

    def __init__(self, store: FarmStore, mongo_store: MongoTelemetryStore | None = None) -> None:
        self.iot = FieldIoTAgent(store, mongo_store=mongo_store)
        self.irrigation = IrrigationPlanningAgent()
        self.resources = ResourceAgent()
        self.actions = FarmActionAgent(store)

    def handle(self, request: str, manager_name: str) -> dict[str, Any]:
        observation = self.iot.observe()
        irrigation = self.irrigation.plan(observation)
        resources = self.resources.check(observation, irrigation)
        action = self.actions.create(irrigation, resources, observation["evidence"])
        return {
            "manager_request": request,
            "manager": manager_name,
            "coordinator": self.name,
            "agent_trace": [observation, irrigation, resources, action],
            "summary": irrigation["reason"] if resources["approved"] else f"{irrigation['reason']} {resources['reason']}",
        }
