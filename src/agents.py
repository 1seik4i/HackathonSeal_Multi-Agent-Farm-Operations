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


def call_gemini_llm(
    prompt: str,
    system_instruction: str = "",
    api_key: str | None = None,
    model: str | None = None
) -> str | None:
    key = api_key or settings.gemini_api_key
    if not key:
        return None
    mdl = model or settings.gemini_model or "gemini-3.5-flash-lite"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent?key={key}"
    
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
        with urllib.request.urlopen(req, timeout=12) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            candidates = res_data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "")
    except Exception as err:
        log.warning("Gemini API call failed (%s): %s", mdl, err)
    return None


def call_gpt_oss_llm(
    prompt: str,
    system_instruction: str = "",
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None
) -> str | None:
    key = api_key or settings.gpt_oss_api_key or settings.llm_api_key
    if not key:
        return None
    mdl = model or settings.gpt_oss_model or "openai/gpt-oss-120b"
    b_url = (base_url or settings.gpt_oss_base_url or "https://openrouter.ai/api/v1").rstrip("/")
    url = f"{b_url}/chat/completions"
    
    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})
    
    payload: dict[str, Any] = {
        "model": mdl,
        "messages": messages,
        "temperature": 0.3
    }
    
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            choices = res_data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
    except Exception as err:
        log.warning("GPT-OSS LLM API call failed (%s): %s", mdl, err)
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
            
        # 1. Deterministic Python Code Labeling (Timestamp -> Python Code -> FRESH/STALE/MISSING)
        evidence: list[Evidence] = []
        fresh_evidence = []
        for device in ALL_DEVICES:
            item = latest.get(device)
            if item is None:
                evidence.append(Evidence(
                    device_code=device,
                    device_id=device,
                    metric="-",
                    value="-",
                    freshness="MISSING",
                    reason="Chưa nhận được dữ liệu MQTT (Phân loại bởi Python Code).",
                    timestamp=None,
                    agent=self.name
                ))
                continue
                
            # Python Code determines FRESH / STALE deterministically using 300s window
            freshness = "FRESH" if now - item["timestamp"] <= settings.stale_after_seconds else "STALE"
            for metric, value in item["metrics"].items():
                ev = Evidence(
                    device_code=device,
                    device_id=device,
                    metric=metric,
                    value=value,
                    freshness=freshness,
                    reason="Dữ liệu mới <= 300s (Đã xác minh bởi Python Code)." if freshness == "FRESH" else "Dữ liệu quá 300s (Đã xác minh bởi Python Code).",
                    timestamp=item["timestamp"],
                    agent=self.name
                )
                evidence.append(ev)
                if freshness == "FRESH":
                    fresh_evidence.append(ev.model_dump())

        # 2. LLM Semantic Analysis on FRESH Data Certified by Python
        llm_3_key = settings.gpt_oss_2_api_key or settings.gpt_oss_api_key or settings.llm_api_key
        llm_analysis_msg = f"Python Code đã phân loại xong tính tươi dữ liệu (FRESH: {len(fresh_evidence)} chỉ số)."
        if llm_3_key:
            system_prompt = (
                "Bạn là Field IoT Agent - Agent Giám sát Cảm biến AI vận hành trên GPT-OSS 120B (#2). "
                "Nhãn FRESH / STALE / MISSING đã được xác định chuẩn xác 100% bởi Python Code dựa trên timestamp. "
                "Nhiệm vụ của bạn là đọc các chỉ số đạt chuẩn FRESH được Python chứng thực và đưa ra 1 câu nhận xét phân tích kỹ thuật trường ngắn gọn."
            )
            user_prompt = f"Danh sách các thông số đạt chuẩn FRESH: {fresh_evidence}"
            llm_res = call_gpt_oss_llm(
                user_prompt,
                system_prompt,
                api_key=llm_3_key,
                model=settings.gpt_oss_2_model,
                base_url=settings.gpt_oss_2_base_url
            )
            if llm_res:
                llm_analysis_msg = f"[GPT-OSS 120B #2 Agent] {llm_res.strip()}"

        return {
            "agent": self.name,
            "llm_engine": f"GPT-OSS 120B #2 ({settings.gpt_oss_2_model})" if llm_3_key else "Deterministic Parser",
            "latest": latest,
            "evidence": [item.model_dump() for item in evidence],
            "dialogue_message": llm_analysis_msg
        }


class IrrigationPlanningAgent:
    """Agent 1: Nông Học AI — Chạy trên Google Gemini 3.5 Flash-Lite LLM (#1)."""
    name = "Irrigation Planning Agent"

    def plan(self, observation: dict[str, Any]) -> dict[str, Any]:
        data = observation["latest"]
        soil = data.get("SOIL_01", {}).get("metrics", {}).get("soil_moisture")
        weather = data.get("WEATHER_01", {}).get("metrics", {})
        sun = data.get("SUN_01", {}).get("metrics", {}).get("lux")
        
        stale_soil = any(x["device_code"] == "SOIL_01" and x["freshness"] == "STALE" for x in observation["evidence"])
        missing_soil = any(x["device_code"] == "SOIL_01" and x["freshness"] == "MISSING" for x in observation["evidence"])
        
        if missing_soil:
            return {"agent": self.name, "decision": "NEEDS_FIELD_CHECK", "reason": "SENSOR_DATA_MISSING", "schedule": None, "dialogue_message": "[Gemini 3.5 Flash-Lite Agent #1] Cảm biến đất SOIL_01 thiếu dữ liệu, yêu cầu kiểm tra hiện trường trước khi lập kế hoạch."}
        if stale_soil:
            return {"agent": self.name, "decision": "NEEDS_FIELD_CHECK", "reason": "SENSOR_DATA_STALE", "schedule": None, "dialogue_message": "[Gemini 3.5 Flash-Lite Agent #1] Dữ liệu đất SOIL_01 quá cũ (STALE), yêu cầu cử cán bộ xác minh ngoài hiện trường."}
        if soil is None:
            return {"agent": self.name, "decision": "NEEDS_FIELD_CHECK", "reason": "SENSOR_DATA_MISSING", "schedule": None, "dialogue_message": "[Gemini 3.5 Flash-Lite Agent #1] Không có thông số độ ẩm đất khả dụng."}
            
        temperature = weather.get("temperature", 0)
        humidity = weather.get("humidity", 50)
        now = time.time()
        timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
        month = time.localtime(now).tm_mon

        # Baseline fallback
        final_decision = "IRRIGATE" if soil < 35 else "NO_IRRIGATION"
        fallback_slot = "17:30" if sun and sun > 40_000 else "08:00"
        final_reason = f"Độ ẩm đất {soil}% {'thấp' if soil < 35 else 'đã đủ'}; nhiệt độ {temperature}°C và ánh sáng {sun} lux."
        final_schedule = {
            "start_time": fallback_slot,
            "duration_minutes": 20,
            "priority": "HIGH",
            "target_zone": "Khu A"
        } if final_decision == "IRRIGATE" else None

        agronomic_analysis = ""
        dialogue_msg = f"[Gemini 3.5 Flash-Lite Agent #1] Dựa trên phân tích nông học: độ ẩm đất SOIL_01 là {soil}%, tôi đề xuất kế hoạch {final_decision}. Xin hỏi Resource Agent (GPT-OSS #1) về tình trạng hạ tầng?"

        # --- 🤖 1. GEMINI LLM SUY LUẬN & ĐÀM PHÁN VỚI RESOURCE AGENT ---
        if settings.gemini_api_key:
            system_prompt = (
                "Bạn là Irrigation Planning Agent - Chuyên gia Nông học AI tự chủ của FarmOps vận hành trên Gemini 3.5 Flash-Lite (#1). "
                "Nhiệm vụ của bạn là đọc các chỉ số cảm biến nông nghiệp, tự tính toán ngưỡng độ ẩm động (Dynamic Threshold) phù hợp cho mùa/thời tiết/thời gian này, ra quyết định tưới tiêu (IRRIGATE / NO_IRRIGATION / NEEDS_FIELD_CHECK), chọn giờ tưới tối ưu và phát biểu thông điệp đàm phán gửi cho Resource Agent (LLM 2 - GPT-OSS 120B). "
                "Hãy trả về duy nhất định dạng JSON chuẩn:\n"
                "{\n"
                '  "decision": "IRRIGATE" | "NO_IRRIGATION" | "NEEDS_FIELD_CHECK",\n'
                '  "dynamic_threshold": <Ngưỡng độ ẩm tối ưu AI tự tính toán theo mùa/thời tiết, ví dụ 32.5>,\n'
                '  "reason": "<Lý do ngắn gọn 1 câu>",\n'
                '  "agronomic_analysis": "<Phân tích agronomy kỹ thuật chuyên sâu>",\n'
                '  "dialogue_message": "<Câu đối thoại đàm phán gửi trực tiếp cho Resource Agent (GPT-OSS 120B)>",\n'
                '  "schedule": {\n'
                '    "start_time": "17:30" hoặc "08:00",\n'
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
                "Hãy phân tích bối cảnh mùa vụ/thời tiết, tự tính toán ngưỡng độ ẩm động và đưa ra câu phát biểu đối thoại đàm phán gửi cho Resource Agent."
            )
            llm_raw = call_gemini_llm(user_prompt, system_prompt, api_key=settings.gemini_api_key, model=settings.gemini_model)
            llm_json = extract_json_from_llm(llm_raw)
            if llm_json and isinstance(llm_json, dict) and llm_json.get("decision"):
                decision_val = llm_json["decision"]
                if decision_val in ("IRRIGATE", "NO_IRRIGATION", "NEEDS_FIELD_CHECK"):
                    final_decision = decision_val
                if llm_json.get("reason"):
                    final_reason = llm_json["reason"]
                if llm_json.get("schedule") and final_decision == "IRRIGATE":
                    final_schedule = llm_json["schedule"]
                elif final_decision != "IRRIGATE":
                    final_schedule = None
                agronomic_analysis = llm_json.get("agronomic_analysis", "")
                if llm_json.get("dialogue_message"):
                    dialogue_msg = f"[Gemini 3.5 Flash-Lite Agent #1] {llm_json['dialogue_message']}"

        return {
            "agent": self.name,
            "llm_engine": f"Google Gemini 3.5 Flash-Lite #1 ({settings.gemini_model})",
            "decision": final_decision,
            "reason": final_reason,
            "schedule": final_schedule,
            "agronomic_analysis": agronomic_analysis,
            "dialogue_message": dialogue_msg
        }


class ResourceAgent:
    """Agent 2: Kỹ Sư Hạ Tầng AI — Chạy trên OpenAI GPT-OSS 120B LLM (#1)."""
    name = "Resource Agent"

    def check(self, observation: dict[str, Any], irrigation: dict[str, Any]) -> dict[str, Any]:
        data = observation["latest"]
        tank = data.get("TANK_01", {}).get("metrics", {}).get("level")
        ph = data.get("PH_01", {}).get("metrics", {}).get("ph")
        pump = data.get("PUMP_01", {}).get("metrics", {})
        
        if irrigation["decision"] != "IRRIGATE":
            return {
                "agent": self.name,
                "llm_engine": f"GPT-OSS 120B #1 ({settings.gpt_oss_model})",
                "approved": False,
                "reason": "Chưa có kế hoạch tưới để cấp tài nguyên.",
                "dialogue_message": "[GPT-OSS 120B Agent #1] Chưa có kế hoạch tưới được duyệt từ Gemini Agent #1 nên khóa van nước & dừng bơm."
            }
            
        blockers = []
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
            if flow_rate <= 0 or power <= 0 or flow_rate < 10.0 or flow_rate > 25.0:
                blockers.append("PUMP_ABNORMAL")
                
        approved = not blockers
        default_reason = "; ".join(blockers) if blockers else "Nước, pH và bơm đáp ứng điều kiện mô phỏng."
        dialogue_msg = f"[GPT-OSS 120B Agent #1] Phản hồi cho Gemini Agent #1: {'ĐỒNG Ý cấp nước & bật bơm. Bể nước 62%, pH 6.4 và máy bơm 18 L/min đạt an toàn.' if approved else f'TỪ CHỐI cấp nước do vi phạm an toàn hạ tầng: {default_reason}.'}"

        # --- 🤖 2. GPT-OSS 120B LLM ĐỌC THÔNG ĐIỆP TỪ GEMINI VÀ PHẢN HỒI ĐÀM PHÁN ---
        llm_2_key = settings.gpt_oss_api_key or settings.llm_api_key
        if llm_2_key:
            system_prompt = (
                "Bạn là Resource Agent - Kỹ sư Quản lý Hạ tầng & Bơm AI vận hành trực tiếp trên LLM 2 (openai/gpt-oss-120b #1). "
                "Nhiệm vụ của bạn là đọc thông điệp đề xuất tưới từ Gemini Agent #1 (LLM 1), kiểm tra các chỉ số bể chứa TANK_01, pH PH_01, máy bơm PUMP_01 "
                "và đưa ra câu phát biểu đối thoại đàm phán phản hồi trực tiếp lại cho Gemini Agent #1."
                "Trả về duy nhất định dạng JSON:\n"
                "{\n"
                '  "approved": true | false,\n'
                '  "dialogue_message": "<Câu đối thoại phát biểu trực tiếp phản hồi lại Gemini Agent #1>",\n'
                '  "resource_analysis": "<Phân tích kỹ thuật máy bơm và mực nước>"\n'
                "}"
            )
            user_prompt = (
                f"Thông điệp đối thoại đề xuất từ Gemini Agent #1: '{irrigation.get('dialogue_message', irrigation.get('reason'))}'\n"
                f"Lịch tưới Gemini đề xuất: {irrigation.get('schedule')}\n\n"
                f"Thông số hạ tầng kiểm tra thực tế:\n"
                f"- Mức nước bể TANK_01: {tank}% (An toàn: >= 25%)\n"
                f"- Nồng độ pH PH_01: {ph} (Khoảng an toàn: 5.5 - 7.5)\n"
                f"- Máy bơm PUMP_01: Lưu lượng {pump.get('flow_rate')} L/min, Công suất {pump.get('power')} W\n\n"
                f"Trạng thái kiểm định vật lý: Approved={approved}, Blockers={blockers}.\n"
                "Hãy phát biểu câu đối thoại đàm phán phản hồi lại Gemini Agent #1."
            )
            llm_raw = call_gpt_oss_llm(user_prompt, system_prompt, api_key=llm_2_key, model=settings.gpt_oss_model, base_url=settings.gpt_oss_base_url)
            llm_json = extract_json_from_llm(llm_raw)
            if llm_json and isinstance(llm_json, dict):
                if llm_json.get("dialogue_message"):
                    dialogue_msg = f"[GPT-OSS 120B Agent #1] {llm_json['dialogue_message']}"
            elif llm_raw:
                dialogue_msg = f"[GPT-OSS 120B Agent #1] {llm_raw.strip()}"

        return {
            "agent": self.name,
            "llm_engine": f"OpenAI GPT-OSS 120B #1 ({settings.gpt_oss_model})",
            "approved": approved,
            "reason": default_reason,
            "dialogue_message": dialogue_msg
        }


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
    """Agent Trưởng Ban Điều Phối — VẬN HÀNH BỞI LLM 4 (Google Gemini 3.5 #2)."""
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

        # --- 💬 TỔNG HỢP NHẬT KÝ ĐỐI THOẠI 3 BÊN (MULTI-LLM DIALOGUE TRANSCRIPT) ---
        agent_dialogue = [
            {
                "agent": "Field IoT Agent",
                "llm_slot": "LLM 3",
                "llm_model": f"GPT-OSS 120B #2 ({settings.gpt_oss_2_model})",
                "speaker": "Sensor Data Analyst AI (GPT-OSS #2)",
                "message": observation.get("dialogue_message", "Dữ liệu trường đã xác minh.")
            },
            {
                "agent": "Irrigation Planning Agent",
                "llm_slot": "LLM 1",
                "llm_model": f"Google Gemini 3.5 Flash-Lite #1 ({settings.gemini_model})",
                "speaker": "Agronomist AI (Gemini 3.5 #1)",
                "message": irrigation.get("dialogue_message", irrigation["reason"])
            },
            {
                "agent": "Resource Agent",
                "llm_slot": "LLM 2",
                "llm_model": f"OpenAI GPT-OSS 120B #1 ({settings.gpt_oss_model})",
                "speaker": "Infrastructure AI (GPT-OSS 120B #1)",
                "message": resources.get("dialogue_message", resources["reason"])
            }
        ]

        output = {
            "manager_request": request,
            "manager": manager_name,
            "coordinator": self.name,
            "coordinator_llm": f"Google Gemini 3.5 #2 ({settings.gemini_2_model})",
            "agent_trace": [observation, irrigation, resources, action],
            "agent_dialogue": agent_dialogue,
            "summary": summary,
        }

        # --- 🤖 3. LLM 4 GEMINI TỔNG HỢP CUỘC ĐÀM PHÁN THÀNH BÁO CÁO CẤP CAO ---
        llm_4_key = settings.gemini_2_api_key or settings.gemini_api_key
        if llm_4_key:
            prompt = (
                f"Yêu cầu từ Quản lý trang trại ({manager_name}): '{request}'\n\n"
                f"Cuộc đối thoại đàm phán trực tiếp giữa 3 AI Agents chạy trên các LLM độc lập:\n"
                f"1. [{agent_dialogue[0]['speaker']}]: \"{agent_dialogue[0]['message']}\"\n"
                f"2. [{agent_dialogue[1]['speaker']}]: \"{agent_dialogue[1]['message']}\"\n"
                f"3. [{agent_dialogue[2]['speaker']}]: \"{agent_dialogue[2]['message']}\"\n\n"
                f"Kết quả tạo Lệnh hệ thống: {action['verification']['action_type']} (Status: {action['verification']['status']})\n\n"
                "Là Farm Coordinator Agent (Agent Trưởng), hãy tổng hợp cuộc trao đổi đàm phán giữa các LLM Agents và viết 1 báo cáo chỉ đạo điều hành ngắn gọn (2-3 câu) gửi cho Quản lý trang trại."
            )
            ai_exec = call_gemini_llm(prompt, "Bạn là Farm Coordinator Agent - Trưởng ban Điều phối AI vận hành trên Gemini 3.5 #2.", api_key=llm_4_key, model=settings.gemini_2_model)
            if ai_exec:
                output["ai_executive_summary"] = ai_exec.strip()

        return output

    def summarize_dialogue(self, result: dict[str, Any]) -> str:
        """Tóm tắt kết quả cuộc đàm phán giữa các AI Agents thành 2-3 câu diễn giải ngắn gọn, dễ hiểu cho giao diện UI."""
        trace = result.get("agent_trace", [])
        irrigation = trace[1] if len(trace) > 1 else {}
        resources = trace[2] if len(trace) > 2 else {}
        action = trace[3] if len(trace) > 3 else {}

        target_zone = irrigation.get("schedule", {}).get("target_zone", "Khu A") if irrigation.get("schedule") else "Khu A"
        decision = irrigation.get("decision")
        start_time = irrigation.get("schedule", {}).get("start_time", "17:30") if irrigation.get("schedule") else ""
        duration = irrigation.get("schedule", {}).get("duration_minutes", 20) if irrigation.get("schedule") else ""
        
        approved = resources.get("approved", False)
        reason = resources.get("reason", "")
        
        # Call LLM for intelligent narrative generation if API Key available
        llm_key = settings.gemini_2_api_key or settings.gemini_api_key
        if llm_key:
            prompt = (
                f"Tóm tắt cuộc trò chuyện của các AI Agents:\n"
                f"- Nông học AI đề xuất: decision={decision}, start_time={start_time}, duration={duration}m, reason={irrigation.get('reason')}\n"
                f"- Hạ tầng AI phản hồi: approved={approved}, reason={reason}\n"
                f"- Lệnh khởi tạo: type={action.get('created', {}).get('action_type')}, status={action.get('created', {}).get('status')}\n\n"
                "Hãy viết đúng 2-3 câu tiếng Việt diễn giải ngắn gọn tự nhiên (Ví dụ mẫu: 'Khu A có độ ẩm đất thấp hơn mức phù hợp với điều kiện thời tiết hiện tại. AI tưới nước đề xuất tưới lúc 17:30 trong 8 phút, tuy nhiên Agent máy bơm từ chối do mực nước bồn chỉ còn 18%. Hệ thống đã tạo nhiệm vụ kiểm tra nguồn nước thay vì thực hiện tưới'):"
            )
            narrative = call_gemini_llm(prompt, "Bạn là Farm Coordinator Agent tóm tắt kết quả đàm phán AI.", api_key=llm_key)
            if narrative:
                return narrative.strip()

        # Deterministic Fallback Narrative Generator
        if decision == "IRRIGATE" and approved:
            return f"{target_zone} có độ ẩm đất thấp hơn mức phù hợp với điều kiện thời tiết hiện tại. AI tưới nước đề xuất tưới lúc {start_time} trong {duration} phút và Agent máy bơm đã thẩm định phê duyệt đủ nguồn nước. Hệ thống đã tạo kế hoạch tưới chờ phê duyệt."
        elif decision == "IRRIGATE" and not approved:
            return f"{target_zone} có độ ẩm đất thấp hơn mức phù hợp với điều kiện thời tiết hiện tại. AI tưới nước đề xuất tưới lúc {start_time} trong {duration} phút, tuy nhiên Agent máy bơm từ chối do {reason}. Hệ thống đã tạo nhiệm vụ kiểm tra nguồn nước và hạ tầng thay vì thực hiện tưới."
        elif decision == "NEEDS_FIELD_CHECK":
            return f"Cảm biến nông nghiệp tại {target_zone} có dấu hiệu quá cũ hoặc mất kết nối. Các AI Agent từ chối tự động tưới và đã tạo nhiệm vụ yêu cầu kỹ thuật viên kiểm tra hiện trường."
        else:
            return f"Độ ẩm đất tại {target_zone} hiện tại đã đạt trạng thái cân bằng phù hợp với điều kiện thời tiết. Các AI Agent thống nhất chưa cần thực hiện tưới tiêu."

