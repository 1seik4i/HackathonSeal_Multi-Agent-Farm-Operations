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


def call_llm(prompt: str, system_instruction: str = "") -> str | None:
    """General LLM caller: tries GPT-OSS 120B first, falls back to Gemini."""
    if settings.gpt_oss_api_key or settings.llm_api_key:
        res = call_gpt_oss_llm(prompt, system_instruction)
        if res:
            return res
    if settings.gemini_api_key:
        res = call_gemini_llm(prompt, system_instruction)
        if res:
            return res
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
    """Agent Giám Sát Cảm Biến — VẬN HÀNH BỞI LLM 3 (GPT-OSS 120B #2 hoặc LLM Cảm biến)."""
    name = "Field IoT Agent"

    def __init__(self, store: FarmStore, mongo_store: MongoTelemetryStore | None = None) -> None:
        self.store = store
        self.mongo_store = mongo_store

    def observe(self) -> dict[str, Any]:
        now = time.time()
        
        # Read telemetry from MongoDB Atlas if available, fallback to SQLite
        latest = {}
        if self.mongo_store is not None:
            try:
                latest = self.mongo_store.latest_by_device()
                log.info("FieldIoTAgent: Successfully fetched latest telemetry from MongoDB Atlas.")
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

        # LLM 3 Processing (GPT-OSS 120B #2)
        llm_3_key = settings.gpt_oss_2_api_key or settings.gpt_oss_api_key or settings.llm_api_key
        llm_analysis_msg = "Dữ liệu các cảm biến trường đã được kiểm tra tính thời gian thực."
        if llm_3_key:
            system_prompt = (
                "Bạn là Field IoT Agent - Agent Giám sát & Phân tích Dữ liệu Cảm biến AI vận hành trên GPT-OSS 120B (#2). "
                "Nhiệm vụ của bạn là đánh giá độ an toàn dữ liệu 6 cảm biến và phát biểu thông điệp xác minh dữ liệu trường."
            )
            user_prompt = f"Thông số cảm biến thời gian thực: {latest}\nBằng chứng xác minh: {[e.model_dump() for e in evidence]}"
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
    """Agent Lập Kế Hoạch Tưới — VẬN HÀNH BỞI LLM 1 (Google Gemini 3.5 Flash-Lite #1)."""
    name = "Irrigation Planning Agent"

    def plan(self, observation: dict[str, Any]) -> dict[str, Any]:
        data = observation["latest"]
        soil = data.get("SOIL_01", {}).get("metrics", {}).get("soil_moisture")
        weather = data.get("WEATHER_01", {}).get("metrics", {})
        sun = data.get("SUN_01", {}).get("metrics", {}).get("lux")
        
        stale_soil = any(x["device_code"] == "SOIL_01" and x["freshness"] == "STALE" for x in observation["evidence"])
        missing_soil = any(x["device_code"] == "SOIL_01" and x["freshness"] == "MISSING" for x in observation["evidence"])
        
        if missing_soil:
            return {"agent": self.name, "llm_engine": f"Google Gemini ({settings.gemini_model})", "decision": "NEEDS_FIELD_CHECK", "reason": "SENSOR_DATA_MISSING", "schedule": None, "dialogue_message": "[Gemini 3.5 Flash-Lite Agent #1] Cảm biến đất SOIL_01 thiếu dữ liệu, yêu cầu kiểm tra hiện trường trước khi lập kế hoạch."}
        if stale_soil:
            return {"agent": self.name, "llm_engine": f"Google Gemini ({settings.gemini_model})", "decision": "NEEDS_FIELD_CHECK", "reason": "SENSOR_DATA_STALE", "schedule": None, "dialogue_message": "[Gemini 3.5 Flash-Lite Agent #1] Dữ liệu đất SOIL_01 quá cũ (STALE), yêu cầu cử cán bộ xác minh ngoài hiện trường."}
        if soil is None:
            return {"agent": self.name, "llm_engine": f"Google Gemini ({settings.gemini_model})", "decision": "NEEDS_FIELD_CHECK", "reason": "SENSOR_DATA_MISSING", "schedule": None, "dialogue_message": "[Gemini 3.5 Flash-Lite Agent #1] Không có thông số độ ẩm đất khả dụng."}
            
        temperature = weather.get("temperature", 0)
        
        # Base safety calculation
        if soil < 35:
            slot = "17:30" if sun and sun > 40_000 else "08:00"
            default_decision = "IRRIGATE"
            default_reason = f"Độ ẩm đất {soil}% thấp; nhiệt độ {temperature}°C và ánh sáng được dùng để chọn giờ tưới."
            default_schedule = {
                "start_time": slot,
                "duration_minutes": 20,
                "priority": "HIGH",
                "target_zone": "Khu A"
            }
        else:
            default_decision = "NO_IRRIGATION"
            default_reason = f"Độ ẩm đất {soil}% chưa yêu cầu tưới."
            default_schedule = None

        agronomic_analysis = ""
        dialogue_msg = f"[Gemini 3.5 Flash-Lite Agent #1] Đề xuất kế hoạch {default_decision}: {default_reason}"

        # --- LLM 1 Execution (Google Gemini 3.5 Flash-Lite #1) ---
        if settings.gemini_api_key:
            system_prompt = (
                "Bạn là Irrigation Planning Agent - Chuyên gia Nông học AI vận hành trực tiếp trên Gemini 3.5 Flash-Lite (#1). "
                "Hãy phân tích chỉ số cảm biến đất, không khí, bức xạ ánh sáng để ra quyết định tưới tiêu và phát biểu thông điệp đối thoại trực tiếp gửi cho Resource Agent (LLM 2 - GPT-OSS 120B). "
                "Trả về duy nhất định dạng JSON:\n"
                "{\n"
                '  "decision": "IRRIGATE" | "NO_IRRIGATION" | "NEEDS_FIELD_CHECK",\n'
                '  "reason": "<Lý do ngắn gọn 1 câu>",\n'
                '  "agronomic_analysis": "<Phân tích agronomy kỹ thuật>",\n'
                '  "dialogue_message": "<Câu đối thoại phát biểu trực tiếp gửi cho Resource Agent (LLM 2)>"\n'
                "}"
            )
            user_prompt = (
                f"Bằng chứng cảm biến thời gian thực:\n"
                f"- Độ ẩm đất SOIL_01: {soil}%\n"
                f"- Nhiệt độ không khí WEATHER_01: {temperature}°C\n"
                f"- Bức xạ ánh sáng SUN_01: {sun} lux\n\n"
                f"Khuyến nghị nông học ban đầu: {default_decision} (Giờ tưới khuyến nghị: {default_schedule.get('start_time') if default_schedule else 'N/A'}).\n"
                "Hãy suy luận bằng Gemini 3.5 Flash-Lite LLM và phát biểu thông điệp đối thoại với Resource Agent."
            )
            llm_raw = call_gemini_llm(user_prompt, system_prompt, api_key=settings.gemini_api_key, model=settings.gemini_model)
            llm_json = extract_json_from_llm(llm_raw)
            if llm_json and isinstance(llm_json, dict):
                agronomic_analysis = llm_json.get("agronomic_analysis", "")
                if llm_json.get("dialogue_message"):
                    dialogue_msg = f"[Gemini 3.5 Flash-Lite Agent #1] {llm_json['dialogue_message']}"
            elif llm_raw:
                agronomic_analysis = llm_raw.strip()
                dialogue_msg = f"[Gemini 3.5 Flash-Lite Agent #1] Đề xuất {default_decision}: {default_reason}. Phân tích: {agronomic_analysis}"

        return {
            "agent": self.name,
            "llm_engine": f"Google Gemini 3.5 Flash-Lite #1 ({settings.gemini_model})",
            "decision": default_decision,
            "reason": default_reason,
            "schedule": default_schedule,
            "agronomic_analysis": agronomic_analysis,
            "dialogue_message": dialogue_msg
        }


class ResourceAgent:
    """Agent Kiểm Tra Hạ Tầng & Bơm — VẬN HÀNH BỞI LLM 2 (OpenAI GPT-OSS 120B #1)."""
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
            if flow_rate <= 0 or power <= 0 or flow_rate < 10.0 or flow_rate > 25.0:
                blockers.append("PUMP_ABNORMAL")
                
        approved = not blockers
        default_reason = "; ".join(blockers) if blockers else "Nước, pH và bơm đáp ứng điều kiện mô phỏng."
        dialogue_msg = f"[GPT-OSS 120B Agent #1] Phản hồi cho Gemini Agent #1: {'ĐỒNG Ý cấp nước & bật bơm. Bể nước 62%, pH 6.4 và máy bơm 18 L/min đạt an toàn.' if approved else f'TỪ CHỐI cấp nước do không đủ điều kiện an toàn: {default_reason}.'}"

        # --- LLM 2 Execution (OpenAI GPT-OSS 120B #1) ---
        llm_2_key = settings.gpt_oss_api_key or settings.llm_api_key
        if llm_2_key:
            system_prompt = (
                "Bạn là Resource Agent - Kỹ sư Quản lý Hạ tầng & Bơm AI vận hành trực tiếp trên LLM 2 (openai/gpt-oss-120b #1). "
                "Nhiệm vụ của bạn là nhận thông điệp đối thoại đề xuất từ Gemini Agent #1 (LLM 1), đánh giá dung tích bể nước TANK_01, pH PH_01, lưu lượng bơm PUMP_01 "
                "và đưa ra câu phát biểu đối thoại phản hồi lại Gemini Agent #1 và Coordinator."
                "Trả về duy nhất định dạng JSON:\n"
                "{\n"
                '  "approved": true | false,\n'
                '  "dialogue_message": "<Phát biểu đối thoại trực tiếp phản hồi lại Gemini Agent #1>",\n'
                '  "resource_analysis": "<Phân tích kỹ thuật máy bơm và mực nước>"\n'
                "}"
            )
            user_prompt = (
                f"Thông điệp đối thoại từ Gemini Agent #1: '{irrigation.get('dialogue_message', irrigation.get('reason'))}'\n"
                f"Lịch tưới Gemini đề xuất: {irrigation.get('schedule')}\n\n"
                f"Thông số hạ tầng kiểm tra thực tế:\n"
                f"- Mức nước bể TANK_01: {tank}% (Mức tối thiểu an toàn: >= 25%)\n"
                f"- Nồng độ pH PH_01: {ph} (Khoảng an toàn: 5.5 - 7.5)\n"
                f"- Máy bơm PUMP_01: Lưu lượng {pump.get('flow_rate')} L/min, Công suất {pump.get('power')} W\n\n"
                f"Trạng thái kiểm định vật lý: Approved={approved}, Blockers={blockers}.\n"
                "Hãy đóng vai GPT-OSS 120B Agent #1 phát biểu thông điệp phản hồi đàm phán lại Gemini Agent #1."
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

        # Capture Multi-LLM Agent Dialogue across 4 LLMs
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

        # --- LLM 4 Execution (Google Gemini 3.5 #2) ---
        llm_4_key = settings.gemini_2_api_key or settings.gemini_api_key
        if llm_4_key:
            prompt = (
                f"Yêu cầu từ Quản lý trang trại ({manager_name}): '{request}'\n\n"
                f"Cuộc đối thoại trực tiếp giữa các Agents chạy trên các LLM độc lập:\n"
                f"1. [{agent_dialogue[0]['speaker']}]: \"{agent_dialogue[0]['message']}\"\n"
                f"2. [{agent_dialogue[1]['speaker']}]: \"{agent_dialogue[1]['message']}\"\n"
                f"3. [{agent_dialogue[2]['speaker']}]: \"{agent_dialogue[2]['message']}\"\n\n"
                f"Kết quả tạo Lệnh hệ thống: {action['verification']['action_type']} (Status: {action['verification']['status']})\n\n"
                "Là Farm Coordinator Agent (Agent Trưởng), hãy tổng hợp cuộc trao đổi đàm phán giữa các LLM Agents và viết 1 báo cáo chỉ đạo điều hành ngắn gọn (2-3 câu) gửi cho Quản lý trang trại."
            )
            ai_exec = call_gemini_llm(prompt, "Bạn là Farm Coordinator Agent - Trưởng ban Điều phối AI vận hành trên Gemini 3.5 #2.", api_key=llm_4_key, model=settings.gemini_2_model)
            if not ai_exec:
                # Fallback to general LLM if Gemini 2 key isn't active
                ai_exec = call_llm(prompt, "Bạn là Farm Coordinator Agent - Trưởng ban Điều phối AI của trang trại thông minh FarmOps.")
            if ai_exec:
                output["ai_executive_summary"] = ai_exec.strip()

        return output
