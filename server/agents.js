import dotenv from "dotenv";
import { getSettings, resolveLlm } from "./runtime_settings.js";
dotenv.config();

const ALL_DEVICES = ["SOIL_01", "WEATHER_01", "PUMP_01", "PH_01", "TANK_01", "SUN_01"];

export async function callGeminiLLMWithStatus(prompt, systemInstruction = "", apiKey = null, model = null) {
  const llm = resolveLlm();
  const key = apiKey || llm.gemini_api_key;
  const mdl = model || llm.gemini_model || "gemini-3.5-flash-lite";

  if (!key) {
    return { text: null, ok: false, error: `Thiếu Gemini API Key (Model: ${mdl})` };
  }

  const url = `https://generativelanguage.googleapis.com/v1beta/models/${mdl}:generateContent?key=${key}`;
  const payload = {
    contents: [{ parts: [{ text: prompt }] }],
  };
  if (systemInstruction) {
    payload.system_instruction = { parts: [{ text: systemInstruction }] };
  }

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 8000); // 8s timeout

    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    clearTimeout(timeoutId);

    if (!resp.ok) {
      const errText = await resp.text().catch(() => "");
      return { text: null, ok: false, error: `HTTP ${resp.status} ${resp.statusText}: ${errText.substring(0, 120)}` };
    }

    const resData = await resp.json();
    const candidates = resData.candidates || [];
    if (candidates.length > 0) {
      const parts = candidates[0].content?.parts || [];
      if (parts.length > 0) return { text: parts[0].text, ok: true, error: null };
    }
    return { text: null, ok: false, error: "API trả về phản hồi rỗng hoặc sai cấu trúc candidates" };
  } catch (err) {
    console.warn(`[Gemini LLM Call Failed] (${mdl}):`, err.message);
    const msg = err.name === "AbortError" ? "API Timeout (> 8 giây không phản hồi)" : err.message;
    return { text: null, ok: false, error: msg };
  }
}

export async function callGeminiLLM(prompt, systemInstruction = "", apiKey = null, model = null) {
  const res = await callGeminiLLMWithStatus(prompt, systemInstruction, apiKey, model);
  return res.text;
}

export async function callGptOssLLMWithStatus(prompt, systemInstruction = "", apiKey = null, model = null, baseUrl = null) {
  const llm = resolveLlm();
  const key = apiKey || llm.gpt_oss_api_key;
  const mdl = model || llm.gpt_oss_model || "openai/gpt-oss-120b";
  const bUrl = (baseUrl || llm.gpt_oss_base_url || "https://openrouter.ai/api/v1").replace(/\/+$/, "");

  if (!key) {
    return { text: null, ok: false, error: `Thiếu GPT-OSS API Key (Model: ${mdl})` };
  }

  const url = `${bUrl}/chat/completions`;
  const messages = [];
  if (systemInstruction) messages.push({ role: "system", content: systemInstruction });
  messages.push({ role: "user", content: prompt });

  const payload = { model: mdl, messages, temperature: 0.3 };

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 8000); // 8s timeout

    const resp = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${key}`,
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    clearTimeout(timeoutId);

    if (!resp.ok) {
      const errText = await resp.text().catch(() => "");
      return { text: null, ok: false, error: `HTTP ${resp.status} ${resp.statusText}: ${errText.substring(0, 120)}` };
    }

    const resData = await resp.json();
    const choices = resData.choices || [];
    if (choices.length > 0) {
      return { text: choices[0].message?.content || "", ok: true, error: null };
    }
    return { text: null, ok: false, error: "API trả về mảng choices rỗng" };
  } catch (err) {
    console.warn(`[GPT-OSS LLM Call Failed] (${mdl}):`, err.message);
    const msg = err.name === "AbortError" ? "API Timeout (> 8 giây không phản hồi)" : err.message;
    return { text: null, ok: false, error: msg };
  }
}

export async function callGptOssLLM(prompt, systemInstruction = "", apiKey = null, model = null, baseUrl = null) {
  const res = await callGptOssLLMWithStatus(prompt, systemInstruction, apiKey, model, baseUrl);
  return res.text;
}

export function extractJsonFromLLM(text) {
  if (!text) return null;
  let cleaned = text.trim();
  if (cleaned.includes("```json")) {
    cleaned = cleaned.split("```json")[1].split("```")[0].trim();
  } else if (cleaned.includes("```")) {
    cleaned = cleaned.split("```")[1].split("```")[0].trim();
  }
  try {
    return JSON.parse(cleaned);
  } catch (e) {
    const start = cleaned.indexOf("{");
    const end = cleaned.lastIndexOf("}");
    if (start !== -1 && end !== -1) {
      try {
        return JSON.parse(cleaned.substring(start, end + 1));
      } catch (err) {}
    }
  }
  return null;
}

export class FieldIoTAgent {
  constructor(store, mongoStore = null) {
    this.name = "Field IoT Agent";
    this.store = store;
    this.mongoStore = mongoStore;
  }

  async observe() {
    const now = Date.now() / 1000;
    const staleAfterSeconds = getSettings().stale_after_seconds || parseInt(process.env.STALE_AFTER_SECONDS || "300", 10);

    let latest = {};
    if (this.mongoStore && this.mongoStore.connected) {
      try {
        latest = await this.mongoStore.latestByDevice();
      } catch (err) {
        latest = await this.store.latestByDevice();
      }
    } else {
      latest = await this.store.latestByDevice();
    }

    const evidence = [];
    const freshEvidence = [];

    for (const device of ALL_DEVICES) {
      const item = latest[device];
      if (!item) {
        evidence.push({
          device_code: device,
          device_id: device,
          metric: "-",
          value: "-",
          freshness: "MISSING",
          reason: "Chưa nhận được dữ liệu MQTT (Phân loại bởi Node.js Code).",
          timestamp: null,
          agent: this.name,
        });
        continue;
      }

      const freshness = now - item.timestamp <= staleAfterSeconds ? "FRESH" : "STALE";
      for (const [metric, value] of Object.entries(item.metrics)) {
        const ev = {
          device_code: device,
          device_id: device,
          metric,
          value,
          freshness,
          reason:
            freshness === "FRESH"
              ? "Dữ liệu mới <= 300s (Đã xác minh bởi Node.js Code)."
              : "Dữ liệu quá 300s (Đã xác minh bởi Node.js Code).",
          timestamp: item.timestamp,
          agent: this.name,
        };
        evidence.push(ev);
        if (freshness === "FRESH") freshEvidence.push(ev);
      }
    }

    const llm = resolveLlm();
    const gptKey = llm.gpt_oss_2_api_key;
    let llmAnalysisMsg = `Node.js Code đã phân loại xong tính tươi dữ liệu (FRESH: ${freshEvidence.length} chỉ số).`;
    let status = "OK";
    let error = null;
    let fallbackUsed = false;

    if (gptKey) {
      const systemPrompt =
        "Bạn là Field IoT Agent - Agent Giám sát Cảm biến AI vận hành trên GPT-OSS 120B (#2). " +
        "Nhãn FRESH / STALE / MISSING đã được xác định chuẩn xác 100% bởi Node.js Code dựa trên timestamp. " +
        "Nhiệm vụ của bạn là đọc các chỉ số đạt chuẩn FRESH được chứng thực và đưa ra 1 câu nhận xét phân tích kỹ thuật trường ngắn gọn.";
      const userPrompt = `Danh sách các thông số đạt chuẩn FRESH: ${JSON.stringify(freshEvidence)}`;
      
      const llmRes = await callGptOssLLMWithStatus(
        userPrompt,
        systemPrompt,
        gptKey,
        llm.gpt_oss_2_model,
        llm.gpt_oss_base_url
      );

      if (llmRes.ok && llmRes.text) {
        llmAnalysisMsg = `[GPT-OSS Agent] ${llmRes.text.trim()}`;
      } else {
        status = "FAILED";
        error = llmRes.error || "GPT-OSS LLM không phản hồi";
        fallbackUsed = true;
        llmAnalysisMsg = `[Field IoT Agent - LỖI AI: ${error}] ⚠️ Đã tự động kích hoạt bộ xử lý Thuần Logic: Node.js đã phân loại xong tính tươi dữ liệu (FRESH: ${freshEvidence.length} chỉ số).`;
      }
    } else {
      status = "FAILED";
      error = "Thiếu API Key cho GPT-OSS #2";
      fallbackUsed = true;
      llmAnalysisMsg = `[Field IoT Agent - LỖI AI: ${error}] ⚠️ Vận hành ở Chế độ Thuần Logic: Node.js đã phân loại xong tính tươi dữ liệu (FRESH: ${freshEvidence.length} chỉ số).`;
    }

    return {
      agent: this.name,
      agent_status: status,
      error,
      fallback_used: fallbackUsed,
      llm_engine: `GPT-OSS (${llm.gpt_oss_2_model})`,
      latest,
      evidence,
      dialogue_message: llmAnalysisMsg,
    };
  }
}

export class IrrigationPlanningAgent {
  constructor() {
    this.name = "Irrigation Planning Agent";
  }

  async plan(observation) {
    const data = observation.latest;
    const soil = data.SOIL_01?.metrics?.soil_moisture;
    const weather = data.WEATHER_01?.metrics || {};
    const sun = data.SUN_01?.metrics?.lux;

    const staleSoil = observation.evidence.some((x) => x.device_code === "SOIL_01" && x.freshness === "STALE");
    const missingSoil = observation.evidence.some((x) => x.device_code === "SOIL_01" && x.freshness === "MISSING");

    if (missingSoil) {
      return {
        agent: this.name,
        agent_status: "OK",
        error: null,
        fallback_used: false,
        decision: "NEEDS_FIELD_CHECK",
        reason: "SENSOR_DATA_MISSING",
        schedule: null,
        dialogue_message: "[Gemini 3.5 Flash-Lite Agent #1] Cảm biến đất SOIL_01 thiếu dữ liệu, yêu cầu kiểm tra hiện trường trước khi lập kế hoạch.",
      };
    }
    if (staleSoil) {
      return {
        agent: this.name,
        agent_status: "OK",
        error: null,
        fallback_used: false,
        decision: "NEEDS_FIELD_CHECK",
        reason: "SENSOR_DATA_STALE",
        schedule: null,
        dialogue_message: "[Gemini 3.5 Flash-Lite Agent #1] Dữ liệu đất SOIL_01 quá cũ (STALE), yêu cầu cử cán bộ xác minh ngoài hiện trường.",
      };
    }
    if (soil === undefined || soil === null) {
      return {
        agent: this.name,
        agent_status: "OK",
        error: null,
        fallback_used: false,
        decision: "NEEDS_FIELD_CHECK",
        reason: "SENSOR_DATA_MISSING",
        schedule: null,
        dialogue_message: "[Gemini 3.5 Flash-Lite Agent #1] Không có thông số độ ẩm đất khả dụng.",
      };
    }

    const temperature = weather.temperature || 0;
    const humidity = weather.humidity || 50;
    const now = new Date();

    // Pure Logic Fallback Rule Calculation:
    // Độ ẩm đất < 35% -> IRRIGATE; ngược lại NO_IRRIGATION
    let finalDecision = soil < 35 ? "IRRIGATE" : "NO_IRRIGATION";
    const fallbackSlot = sun && sun > 40000 ? "17:30" : "08:00";
    const zone = getSettings().target_zone || "Khu A";
    let finalReason = `Độ ẩm đất ${soil}% ${soil < 35 ? "thấp (<35%)" : "đã đủ (>=35%)"}; nhiệt độ ${temperature}°C và ánh sáng ${sun || 0} lux.`;
    let finalSchedule =
      finalDecision === "IRRIGATE"
        ? { start_time: fallbackSlot, duration_minutes: 20, priority: "HIGH", target_zone: zone }
        : null;

    let agronomicAnalysis = "Phân tích nông học thuần logic dựa trên ngưỡng độ ẩm cố định 35%.";
    let dialogueMsg = `[Gemini 3.5 Flash-Lite Agent #1] Độ ẩm đất SOIL_01 là ${soil}%, lập kế hoạch tưới: ${finalDecision}.`;

    const llm = resolveLlm();
    const geminiKey = llm.gemini_api_key;
    let status = "OK";
    let error = null;
    let fallbackUsed = false;

    if (geminiKey) {
      const systemPrompt =
        "Bạn là Irrigation Planning Agent - Chuyên gia Nông học AI tự chủ của FarmOps vận hành trên Gemini 3.5 Flash-Lite (#1). " +
        "Nhiệm vụ của bạn là đọc các chỉ số cảm biến nông nghiệp, tự tính toán ngưỡng độ ẩm động (Dynamic Threshold) phù hợp cho mùa/thời tiết/thời gian này, ra quyết định tưới tiêu (IRRIGATE / NO_IRRIGATION / NEEDS_FIELD_CHECK), chọn giờ tưới tối ưu và phát biểu thông điệp đàm phán gửi cho Resource Agent (LLM 2 - GPT-OSS 120B). " +
        'Trả về duy nhất định dạng JSON chuẩn: {"decision": "IRRIGATE"|"NO_IRRIGATION"|"NEEDS_FIELD_CHECK", "dynamic_threshold": 32.5, "reason": "...", "agronomic_analysis": "...", "dialogue_message": "...", "schedule": {"start_time": "17:30", "duration_minutes": 20, "priority": "HIGH", "target_zone": "Khu A"}}';
      const userPrompt = `Thời điểm đo đạc: ${now.toLocaleString("vi-VN")}\nThông số cảm biến:\n- SOIL_01: ${soil}%\n- WEATHER_01 temp: ${temperature}°C, hum: ${humidity}%\n- SUN_01: ${sun} lux`;

      const llmRes = await callGeminiLLMWithStatus(userPrompt, systemPrompt, geminiKey, llm.gemini_model);
      
      if (llmRes.ok && llmRes.text) {
        const llmJson = extractJsonFromLLM(llmRes.text);
        if (llmJson && llmJson.decision) {
          if (["IRRIGATE", "NO_IRRIGATION", "NEEDS_FIELD_CHECK"].includes(llmJson.decision)) {
            finalDecision = llmJson.decision;
          }
          if (llmJson.reason) finalReason = llmJson.reason;
          if (llmJson.schedule && finalDecision === "IRRIGATE") {
            finalSchedule = { ...llmJson.schedule, target_zone: llmJson.schedule.target_zone || zone };
          } else if (finalDecision !== "IRRIGATE") finalSchedule = null;

          agronomicAnalysis = llmJson.agronomic_analysis || "";
          if (llmJson.dialogue_message) {
            dialogueMsg = `[Gemini 3.5 Flash-Lite Agent #1] ${llmJson.dialogue_message}`;
          }
        } else {
          status = "FAILED";
          error = "Gemini LLM trả về kết quả không khớp định dạng JSON chuẩn";
          fallbackUsed = true;
          dialogueMsg = `[Gemini Agent #1 - LỖI AI: Định dạng JSON lỗi] ⚠️ Đã kích hoạt Lập kế hoạch Thuần Logic: Độ ẩm đất=${soil}%, Kế hoạch=${finalDecision}.`;
        }
      } else {
        status = "FAILED";
        error = llmRes.error || "Gemini LLM không phản hồi";
        fallbackUsed = true;
        dialogueMsg = `[Gemini Agent #1 - LỖI AI: ${error}] ⚠️ Đã tự động chuyển sang CHẾ ĐỘ THUẦN LOGIC: Độ ẩm đất SOIL_01=${soil}%, kế hoạch=${finalDecision}.`;
      }
    } else {
      status = "FAILED";
      error = "Thiếu API Key cho Gemini #1";
      fallbackUsed = true;
      dialogueMsg = `[Gemini Agent #1 - LỖI AI: ${error}] ⚠️ Chạy Chế độ Thuần Logic: Độ ẩm đất SOIL_01=${soil}%, kế hoạch=${finalDecision}.`;
    }

    return {
      agent: this.name,
      agent_status: status,
      error,
      fallback_used: fallbackUsed,
      llm_engine: `Google Gemini (${llm.gemini_model})`,
      decision: finalDecision,
      reason: finalReason,
      schedule: finalSchedule,
      agronomic_analysis: agronomicAnalysis,
      dialogue_message: dialogueMsg,
    };
  }
}

export class ResourceAgent {
  constructor() {
    this.name = "Resource Agent";
  }

  async check(observation, irrigation) {
    const llm = resolveLlm();
    const data = observation.latest;
    const tank = data.TANK_01?.metrics?.level;
    const ph = data.PH_01?.metrics?.ph;
    const pump = data.PUMP_01?.metrics || {};

    if (irrigation.decision !== "IRRIGATE") {
      return {
        agent: this.name,
        agent_status: "OK",
        error: null,
        fallback_used: false,
        llm_engine: `GPT-OSS (${llm.gpt_oss_model})`,
        approved: false,
        reason: "Chưa có kế hoạch tưới để cấp tài nguyên.",
        dialogue_message: "[GPT-OSS Agent] Chưa có kế hoạch tưới được duyệt từ Gemini Agent nên khóa van nước & dừng bơm.",
      };
    }

    // Pure Logic Rule Checks:
    const blockers = [];
    const missingTank = observation.evidence.some((x) => x.device_code === "TANK_01" && x.freshness === "MISSING");
    const staleTank = observation.evidence.some((x) => x.device_code === "TANK_01" && x.freshness === "STALE");
    const missingPump = observation.evidence.some((x) => x.device_code === "PUMP_01" && x.freshness === "MISSING");
    const stalePump = observation.evidence.some((x) => x.device_code === "PUMP_01" && x.freshness === "STALE");

    if (missingTank || staleTank) {
      blockers.push("SENSOR_DATA_MISSING_OR_STALE (TANK_01)");
    } else if (tank === undefined || tank < 25) {
      blockers.push("INSUFFICIENT_WATER (Nước bồn < 25%)");
    }

    if (ph === undefined || ph < 5.5 || ph > 7.5) {
      blockers.push("PH_OUT_OF_RANGE (pH ngoài dải 5.5 - 7.5)");
    }

    if (missingPump || stalePump) {
      blockers.push("SENSOR_DATA_MISSING_OR_STALE (PUMP_01)");
    } else {
      const flowRate = pump.flow_rate || 0;
      const power = pump.power || 0;
      if (flowRate <= 0 || power <= 0 || flowRate < 10.0 || flowRate > 25.0) {
        blockers.push("PUMP_ABNORMAL (Trạng thái bơm bất thường)");
      }
    }

    const approved = blockers.length === 0;
    const defaultReason = blockers.length > 0 ? blockers.join("; ") : "Nước, pH và bơm đáp ứng điều kiện an toàn.";
    let dialogueMsg = `[GPT-OSS Agent] Phản hồi cho Gemini Agent: ${
      approved
        ? "ĐỒNG Ý cấp nước & bật bơm."
        : `TỪ CHỐI cấp nước do vi phạm an toàn hạ tầng: ${defaultReason}.`
    }`;

    const gptKey = llm.gpt_oss_api_key;
    let status = "OK";
    let error = null;
    let fallbackUsed = false;

    if (gptKey) {
      const systemPrompt =
        "Bạn là Resource Agent - Kỹ sư Quản lý Hạ tầng & Bơm AI. " +
        "Nhiệm vụ của bạn là đọc thông điệp đề xuất tưới từ Gemini Agent, kiểm tra các chỉ số bể chứa TANK_01, pH PH_01, máy bơm PUMP_01 " +
        "và đưa ra câu phát biểu đối thoại đàm phán phản hồi trực tiếp lại cho Gemini Agent.\n" +
        'Trả về duy nhất định dạng JSON: {"approved": true|false, "dialogue_message": "...", "resource_analysis": "..."}';
      const userPrompt = `Đề xuất Gemini: '${irrigation.dialogue_message}'\nBể TANK_01: ${tank}%, pH: ${ph}, PUMP: ${JSON.stringify(
        pump
      )}\nStatus: Approved=${approved}, Blockers=${blockers.join(", ")}`;

      const llmRes = await callGptOssLLMWithStatus(userPrompt, systemPrompt, gptKey, llm.gpt_oss_model, llm.gpt_oss_base_url);
      
      if (llmRes.ok && llmRes.text) {
        const llmJson = extractJsonFromLLM(llmRes.text);
        if (llmJson && llmJson.dialogue_message) {
          dialogueMsg = `[GPT-OSS Agent] ${llmJson.dialogue_message}`;
        } else {
          dialogueMsg = `[GPT-OSS Agent] ${llmRes.text.trim()}`;
        }
      } else {
        status = "FAILED";
        error = llmRes.error || "GPT-OSS LLM không phản hồi";
        fallbackUsed = true;
        dialogueMsg = `[Resource Agent - LỖI AI: ${error}] ⚠️ Đã tự động chuyển sang CHẾ ĐỘ THUẦN LOGIC THẨM ĐỊNH: Bồn=${tank}%, pH=${ph}. Kết quả: ${approved ? 'ĐỒNG Ý' : 'TỪ CHỐI (' + defaultReason + ')'}.`;
      }
    } else {
      status = "FAILED";
      error = "Thiếu API Key cho GPT-OSS #1";
      fallbackUsed = true;
      dialogueMsg = `[Resource Agent - LỖI AI: ${error}] ⚠️ Chạy Chế độ Thuần Logic: Bồn=${tank}%, pH=${ph}. Kết quả: ${approved ? 'ĐỒNG Ý' : 'TỪ CHỐI (' + defaultReason + ')'}.`;
    }

    return {
      agent: this.name,
      agent_status: status,
      error,
      fallback_used: fallbackUsed,
      llm_engine: `GPT-OSS (${llm.gpt_oss_model})`,
      approved,
      reason: defaultReason,
      dialogue_message: dialogueMsg,
    };
  }
}

export class FarmActionAgent {
  constructor(store) {
    this.name = "Farm Action Agent";
    this.store = store;
  }

  async create(irrigation, resources, evidence) {
    let action;
    if (irrigation.decision === "IRRIGATE" && resources.approved) {
      action = await this.store.createAction("IRRIGATION_PLAN", "PENDING_APPROVAL", {
        schedule: irrigation.schedule,
        evidence,
        resource_check: resources,
        reason: `Kế hoạch tưới tự động Khu A: Bắt đầu lúc ${irrigation.schedule?.start_time || "17:30"} trong ${
          irrigation.schedule?.duration_minutes || 20
        } phút nhằm bổ sung độ ẩm đất và bảo vệ bơm.`,
      });
    } else {
      let reason = "NO_IRRIGATION_NEEDED";
      if (irrigation.decision === "NEEDS_FIELD_CHECK") {
        reason = irrigation.reason;
      } else if (!resources.approved) {
        const blockers = resources.reason.split("; ");
        reason = blockers[0];
      }
      action = await this.store.createAction("FIELD_TASK", "CREATED", {
        task: "INSPECT_SENSOR_OR_RESOURCE",
        reason,
        evidence,
      });
    }

    return {
      agent: this.name,
      created: action,
      verification: { status: action.status, action_type: action.action_type },
    };
  }
}

export class FarmCoordinatorAgent {
  constructor(store, mongoStore = null) {
    this.name = "Farm Coordinator Agent";
    this.iot = new FieldIoTAgent(store, mongoStore);
    this.irrigation = new IrrigationPlanningAgent();
    this.resources = new ResourceAgent();
    this.actions = new FarmActionAgent(store);
  }

  async handle(requestText, managerName = "Farm Manager") {
    const settings = getSettings();
    const enabled = settings.enabled_agents || {};

    const observation = enabled.field_iot === false
      ? { agent_status: "DISABLED", evidence: [], fresh_evidence: [], latest: {}, dialogue_message: "Field IoT Agent đang tắt trong cài đặt." }
      : await this.iot.observe();

    const irrigation = enabled.irrigation === false
      ? { agent_status: "DISABLED", decision: "HOLD", reason: "Irrigation Agent đang tắt.", schedule: null, dialogue_message: "Irrigation Planning Agent đang tắt." }
      : await this.irrigation.plan(observation);

    const resources = enabled.resource === false
      ? { agent_status: "DISABLED", approved: false, reason: "Resource Agent đang tắt.", dialogue_message: "Resource Agent đang tắt." }
      : await this.resources.check(observation, irrigation);

    const action = enabled.action === false
      ? { created: null, verification: { status: "SKIPPED", action_type: "DISABLED" } }
      : await this.actions.create(irrigation, resources, observation.evidence);

    const summary = resources.approved ? irrigation.reason : `${irrigation.reason} ${resources.reason}`;

    const llmCfg = resolveLlm();
    const agentDialogue = [
      {
        agent: "Field IoT Agent",
        llm_slot: "LLM 3",
        llm_model: `GPT-OSS (${llmCfg.gpt_oss_2_model})`,
        speaker: "Sensor Data Analyst AI",
        message: observation.dialogue_message || "Dữ liệu trường đã xác minh.",
        status: observation.agent_status || "OK",
        error: observation.error || null,
      },
      {
        agent: "Irrigation Planning Agent",
        llm_slot: "LLM 1",
        llm_model: `Google Gemini (${llmCfg.gemini_model})`,
        speaker: "Agronomist AI",
        message: irrigation.dialogue_message || irrigation.reason,
        status: irrigation.agent_status || "OK",
        error: irrigation.error || null,
      },
      {
        agent: "Resource Agent",
        llm_slot: "LLM 2",
        llm_model: `GPT-OSS (${llmCfg.gpt_oss_model})`,
        speaker: "Infrastructure AI",
        message: resources.dialogue_message || resources.reason,
        status: resources.agent_status || "OK",
        error: resources.error || null,
      },
    ];

    // Collect failed agents:
    const failedAgents = [];
    if (observation.agent_status === "FAILED") {
      failedAgents.push({ agent: "Field IoT Agent", model: `GPT-OSS (${llmCfg.gpt_oss_2_model})`, error: observation.error });
    }
    if (irrigation.agent_status === "FAILED") {
      failedAgents.push({ agent: "Irrigation Planning Agent", model: `Google Gemini (${llmCfg.gemini_model})`, error: irrigation.error });
    }
    if (resources.agent_status === "FAILED") {
      failedAgents.push({ agent: "Resource Agent", model: `GPT-OSS (${llmCfg.gpt_oss_model})`, error: resources.error });
    }

    let coordinatorStatus = "OK";
    let coordinatorError = null;

    const gemini2Key = llmCfg.gemini_2_api_key;
    let executiveSummary = "";

    if (gemini2Key) {
      const prompt =
        `Yêu cầu từ Quản lý (${managerName}): '${requestText}'\n\n` +
        `Cuộc đàm phán 3 AI Agents:\n` +
        `1. [${agentDialogue[0].speaker}]: "${agentDialogue[0].message}"\n` +
        `2. [${agentDialogue[1].speaker}]: "${agentDialogue[1].message}"\n` +
        `3. [${agentDialogue[2].speaker}]: "${agentDialogue[2].message}"\n\n` +
        `Kết quả lệnh: ${action.verification.action_type} (Status: ${action.verification.status})\n\n` +
        "Là Farm Coordinator Agent (Agent Trưởng), hãy tổng hợp báo cáo chỉ đạo điều hành 2-3 câu gửi cho Quản lý.";
      
      const aiExec = await callGeminiLLMWithStatus(
        prompt,
        "Bạn là Farm Coordinator Agent - Trưởng ban Điều phối AI.",
        gemini2Key,
        llmCfg.gemini_2_model
      );

      if (aiExec.ok && aiExec.text) {
        executiveSummary = aiExec.text.trim();
      } else {
        coordinatorStatus = "FAILED";
        coordinatorError = aiExec.error || "Gemini Coordinator LLM không phản hồi";
        failedAgents.push({ agent: "Farm Coordinator Agent", model: `Google Gemini (${llmCfg.gemini_2_model})`, error: coordinatorError });
      }
    } else {
      coordinatorStatus = "FAILED";
      coordinatorError = "Thiếu API Key cho Gemini #2 (Coordinator)";
      failedAgents.push({ agent: "Farm Coordinator Agent", model: `Google Gemini (${llmCfg.gemini_2_model})`, error: coordinatorError });
    }

    if (failedAgents.length > 0) {
      const agentNames = failedAgents.map((a) => a.agent).join(", ");
      executiveSummary = `⚠️ CẢNH BÁO VẬN HÀNH: Phát hiện ${failedAgents.length} AI Agent gặp sự cố (${agentNames}). Hệ thống đã LẬP TỨC CHUYỂN SANG CHẾ ĐỘ THUẦN LOGIC (Rule-based Fallback) để duy trì hoạt động nông nghiệp liên tục không gián đoạn! Lệnh phát ra: ${action.verification.action_type} (${action.verification.status}).`;
    }

    const agentHealth = {
      all_ok: failedAgents.length === 0,
      failed_count: failedAgents.length,
      failed_agents: failedAgents,
      fallback_active: failedAgents.length > 0,
      system_notice:
        failedAgents.length > 0
          ? `⚠️ CẢNH BÁO: Phát hiện ${failedAgents.length} AI Agent gặp lỗi (${failedAgents.map((a) => a.agent).join(", ")}). Đã tự động kích hoạt bộ Thuần Logic duy trì vận hành!`
          : "🟢 Tất cả AI Agent đang hoạt động bình thường.",
    };

    return {
      manager_request: requestText,
      manager: managerName,
      coordinator: this.name,
      coordinator_llm: `Google Gemini (${llmCfg.gemini_2_model})`,
      agent_health: agentHealth,
      agent_trace: [observation, irrigation, resources, action],
      agent_dialogue: agentDialogue,
      ai_executive_summary: executiveSummary,
      summary,
    };
  }

  summarizeDialogue(result) {
    const trace = result.agent_trace || [];
    const irrigation = trace[1] || {};
    const resources = trace[2] || {};
    const action = trace[3] || {};

    const targetZone = irrigation.schedule?.target_zone || "Khu A";
    const decision = irrigation.decision;
    const startTime = irrigation.schedule?.start_time || "17:30";
    const duration = irrigation.schedule?.duration_minutes || 20;

    const approved = resources.approved || false;
    const reason = resources.reason || "";
    const isFallback = result.agent_health?.fallback_active;
    const fallbackPrefix = isFallback ? "[CHẾ ĐỘ THUẦN LOGIC] " : "";

    if (decision === "IRRIGATE" && approved) {
      return `${fallbackPrefix}${targetZone} có độ ẩm đất thấp hơn mức phù hợp. Hệ thống đề xuất tưới lúc ${startTime} trong ${duration} phút và thẩm định phê duyệt đủ nguồn nước. Đã tạo kế hoạch tưới chờ phê duyệt.`;
    } else if (decision === "IRRIGATE" && !approved) {
      return `${fallbackPrefix}${targetZone} có độ ẩm đất thấp hơn mức phù hợp. Hệ thống đề xuất tưới lúc ${startTime} trong ${duration} phút, tuy nhiên bị từ chối do ${reason}. Đã tạo nhiệm vụ kiểm tra nguồn nước thay vì thực hiện tưới.`;
    } else if (decision === "NEEDS_FIELD_CHECK") {
      return `${fallbackPrefix}Cảm biến nông nghiệp tại ${targetZone} có dấu hiệu quá cũ hoặc mất kết nối. Hệ thống từ chối tự động tưới và đã tạo nhiệm vụ yêu cầu kiểm tra hiện trường.`;
    }
    return `${fallbackPrefix}Độ ẩm đất tại ${targetZone} hiện tại đã đạt trạng thái cân bằng phù hợp (>= 35%). Thuật toán thống nhất chưa cần thực hiện tưới tiêu.`;
  }
}

