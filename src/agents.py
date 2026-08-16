from __future__ import annotations

import time
from typing import Any

from src.models import Evidence
from src.settings import settings
from src.storage import FarmStore


ALL_DEVICES = ("SOIL_01", "WEATHER_01", "PUMP_01", "PH_01", "TANK_01", "SUN_01")


class FieldIoTAgent:
    name = "Field IoT Agent"

    def __init__(self, store: FarmStore) -> None:
        self.store = store

    def observe(self) -> dict[str, Any]:
        now = time.time()
        latest = self.store.latest_by_device()
        evidence: list[Evidence] = []
        for device in ALL_DEVICES:
            item = latest.get(device)
            if item is None:
                evidence.append(Evidence(device_code=device, metric="-", value="-", freshness="MISSING", reason="Chưa nhận được dữ liệu MQTT."))
                continue
            freshness = "FRESH" if now - item["timestamp"] <= settings.stale_after_seconds else "STALE"
            for metric, value in item["metrics"].items():
                evidence.append(Evidence(
                    device_code=device, metric=metric, value=value, freshness=freshness,
                    reason="Dữ liệu đủ mới để lập kế hoạch." if freshness == "FRESH" else "Dữ liệu đã cũ, cần xác minh ngoài hiện trường.",
                ))
        return {"agent": self.name, "latest": latest, "evidence": [item.model_dump() for item in evidence]}


class IrrigationPlanningAgent:
    name = "Irrigation Planning Agent"

    def plan(self, observation: dict[str, Any]) -> dict[str, Any]:
        data = observation["latest"]
        soil = data.get("SOIL_01", {}).get("metrics", {}).get("soil_moisture")
        weather = data.get("WEATHER_01", {}).get("metrics", {})
        sun = data.get("SUN_01", {}).get("metrics", {}).get("lux")
        stale_soil = any(x["device_code"] == "SOIL_01" and x["freshness"] != "FRESH" for x in observation["evidence"])
        if soil is None or stale_soil:
            return {"agent": self.name, "decision": "NEEDS_FIELD_CHECK", "reason": "Không có dữ liệu độ ẩm đất mới; không bịa lượng tưới.", "schedule": None}
        temperature = weather.get("temperature", 0)
        if soil < 35:
            slot = "17:30" if sun and sun > 40_000 else "08:00"
            return {"agent": self.name, "decision": "IRRIGATE", "reason": f"Độ ẩm đất {soil}% thấp; nhiệt độ {temperature}°C và ánh sáng được dùng để chọn giờ tưới.", "schedule": {"start_time": slot, "duration_minutes": 20, "priority": "HIGH", "target_zone": "Khu A"}}
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
        if tank is None or tank < 25:
            blockers.append("Mực nước bồn thiếu hoặc chưa có dữ liệu.")
        if ph is None or not 5.5 <= ph <= 7.5:
            blockers.append("pH nước nằm ngoài ngưỡng 5.5–7.5 hoặc chưa có dữ liệu.")
        if pump.get("flow_rate", 0) <= 0 or pump.get("power", 0) <= 0:
            blockers.append("Bơm chưa chứng minh đang sẵn sàng: cần flow_rate và power dương.")
        return {"agent": self.name, "approved": not blockers, "reason": "; ".join(blockers) if blockers else "Nước, pH và bơm đáp ứng điều kiện mô phỏng."}


class FarmActionAgent:
    name = "Farm Action Agent"

    def __init__(self, store: FarmStore) -> None:
        self.store = store

    def create(self, irrigation: dict[str, Any], resources: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
        if irrigation["decision"] == "IRRIGATE" and resources["approved"]:
            action = self.store.create_action("IRRIGATION_PLAN", "PENDING_APPROVAL", {"schedule": irrigation["schedule"], "evidence": evidence, "resource_check": resources})
        else:
            action = self.store.create_action("FIELD_TASK", "CREATED", {"task": "INSPECT_SENSOR_OR_RESOURCE", "reason": irrigation["reason"] + " " + resources["reason"], "evidence": evidence})
        verified = self.store.verify_action(action.id)
        return {"agent": self.name, "created": action.model_dump(), "verification": verified.model_dump() if verified else {"status": "FAILED"}}


class FarmCoordinatorAgent:
    name = "Farm Coordinator Agent"

    def __init__(self, store: FarmStore) -> None:
        self.iot = FieldIoTAgent(store)
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

