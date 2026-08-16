import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

from src.models import Evidence
from src.mongo_storage import MongoTelemetryStore
from src.settings import settings
from src.storage import FarmStore

log = logging.getLogger(__name__)

ALL_DEVICES = ("SOIL_01", "WEATHER_01", "PUMP_01", "PH_01", "TANK_01", "SUN_01")


def call_gemini_llm(prompt: str, system_instruction: str = "") -> str | None:
    api_key = settings.gemini_api_key
    if not api_key:
        return None
    model = settings.gemini_model or "gemini-2.0-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    
    payload: dict[str, Any] = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ]
    }
    if system_instruction:
        payload["system_instruction"] = {
            "parts": [{"text": system_instruction}]
        }
        
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            candidates = res_data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "")
    except Exception as err:
        log.warning("Gemini API call failed: %s", err)
    return None


def extract_json_from_llm(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    cleaned = text.strip()
    if "```json" in cleaned:
        cleaned = cleaned.split("```json")[1].split("```")[0].strip()
    elif "```" in cleaned:
        cleaned = cleaned.split("```")[1].split("```")[0].strip()
    try:
        return json.loads(cleaned)
    except Exception:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(cleaned[start:end+1])
            except Exception:
                pass
    return None


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
        humidity = weather.get("humidity", 50)
        now = time.time()
        timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
        month = time.localtime(now).tm_mon

        # --- 🤖 PURE AI DYNAMIC THRESHOLD & REASONING (Gemini LLM) ---
        if settings.gemini_api_key:
            system_prompt = (
                "Bạn là Irrigation Planning Agent - Chuyên gia Nông học AI tự chủ của FarmOps. "
                "Nhiệm vụ của bạn là quan sát thời gian, mùa trong năm (tháng), nhiệt độ, độ ẩm không khí, bức xạ ánh sáng mặt trời (lux) và độ ẩm đất thực tế. "
                "Tuyệt đối KHÔNG dùng ngưỡng gán cứng. Hãy tự động tính toán ngưỡng độ ẩm động (Dynamic Threshold) phù hợp cho mùa/thời tiết/thời gian này. "
                "Sau đó đưa ra quyết định tưới (IRRIGATE / NO_IRRIGATION / NEEDS_FIELD_CHECK), chọn giờ tưới tối ưu (start_time) và thời lượng tưới (duration_minutes). "
                "Hãy trả về duy nhất định dạng JSON chuẩn:\n"
                "{\n"
                '  "decision": "IRRIGATE" | "NO_IRRIGATION" | "NEEDS_FIELD_CHECK",\n'
                '  "dynamic_threshold": <Ngưỡng độ ẩm tối ưu AI tự tính toán theo mùa/thời tiết, ví dụ 32.5>,\n'
                '  "reason": "<Lý do giải thích tại sao chọn ngưỡng này và quyết định>",\n'
                '  "agronomic_analysis": "<Phân tích kỹ thuật agronomy theo mùa và thời tiết>",\n'
                '  "schedule": {\n'
                '    "start_time": "<Giờ tưới tối ưu, ví dụ 17:30>",\n'
                '    "duration_minutes": 20,\n'
                '    "priority": "HIGH",\n'
                '    "target_zone": "Khu A"\n'
                '  }\n'
                "}"
            )
            user_prompt = (
                f"Thời điểm đo đạc: {timestamp_str} (Tháng {month})\n"
                f"Thông số cảm biến thời gian thực:\n"
                f"- Độ ẩm đất SOIL_01: {soil}%\n"
                f"- Nhiệt độ không khí WEATHER_01: {temperature}°C\n"
                f"- Độ ẩm không khí WEATHER_01: {humidity}%\n"
                f"- Bức xạ mặt trời SUN_01: {sun} lux\n\n"
                "Hãy phân tích bối cảnh mùa vụ/thời tiết, tự tính toán ngưỡng độ ẩm động thích hợp và đưa ra quyết định tưới tiêu tối ưu."
            )
            llm_raw = call_gemini_llm(user_prompt, system_prompt)
            llm_json = extract_json_from_llm(llm_raw)
            if llm_json and isinstance(llm_json, dict) and llm_json.get("decision"):
                decision = llm_json["decision"]
                reason = llm_json.get("reason", f"AI phân tích độ ẩm {soil}% theo ngưỡng động {llm_json.get('dynamic_threshold')}%")
                schedule = llm_json.get("schedule") if decision == "IRRIGATE" else None
                return {
                    "agent": self.name,
                    "decision": decision,
                    "dynamic_threshold": llm_json.get("dynamic_threshold"),
                    "reason": reason,
                    "schedule": schedule,
                    "agronomic_analysis": llm_json.get("agronomic_analysis", ""),
                    "llm_reasoning": llm_json.get("agronomic_analysis", reason)
                }

        # Offline Baseline (Chỉ sử dụng khi KHÔNG có API Key)
        decision = "IRRIGATE" if soil < 35 else "NO_IRRIGATION"
        schedule = {"start_time": "17:30", "duration_minutes": 20, "priority": "HIGH", "target_zone": "Khu A"} if decision == "IRRIGATE" else None
        return {
            "agent": self.name,
            "decision": decision,
            "reason": f"Độ ẩm đất {soil}% {'thấp' if soil < 35 else 'đã đủ'} (Offline Fallback Baseline).",
            "schedule": schedule
        }


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
        summary = irrigation["reason"] if resources["approved"] else f"{irrigation['reason']} {resources['reason']}"

        output = {
            "manager_request": request,
            "manager": manager_name,
            "coordinator": self.name,
            "agent_trace": [observation, irrigation, resources, action],
            "summary": summary,
        }

        if settings.gemini_api_key:
            prompt = (
                f"Yêu cầu quản lý ({manager_name}): '{request}'\n"
                f"Kết quả xử lý của các Agent: {summary}\n"
                f"Bằng chứng cảm biến: {observation['evidence']}\n"
                "Hãy viết 1 báo cáo tóm tắt chỉ đạo ngắn gọn, chuyên nghiệp (2-3 câu) cho quản lý trang trại."
            )
            ai_exec = call_gemini_llm(prompt, "Bạn là Farm Coordinator Agent quản lý nông trại thông minh.")
            if ai_exec:
                output["ai_executive_summary"] = ai_exec.strip()

        return output
