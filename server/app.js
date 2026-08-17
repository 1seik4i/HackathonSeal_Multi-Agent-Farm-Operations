import express from "express";
import http from "http";
import cors from "cors";
import path from "path";
import { fileURLToPath } from "url";
import { WebSocketServer } from "ws";
import dotenv from "dotenv";

import { FarmStore } from "./storage.js";
import { MongoTelemetryStore } from "./mongo_storage.js";
import { MQTTIngestionClient } from "./mqtt_service.js";
import { FarmCoordinatorAgent } from "./agents.js";
import { getSettings, updateSettings, updateSecrets, getLlmSlots, getModelCatalog } from "./runtime_settings.js";
import { getFarmMap, saveFarmMap } from "./farm_map.js";

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const PORT = parseInt(process.env.API_PORT || "8000", 10);
const HOST = process.env.API_HOST || "127.0.0.1";

const store = new FarmStore(process.env.DATABASE_PATH || "farmops.db");
const mongoStore = process.env.MONGODB_URI ? new MongoTelemetryStore(process.env.MONGODB_URI, process.env.MONGODB_DB_NAME || "farmops") : null;
const mqttIngestion = new MQTTIngestionClient(store, mongoStore);
const coordinator = new FarmCoordinatorAgent(store, mongoStore);

mqttIngestion.start();

const app = express();
app.use(cors());
app.use(express.json());

const server = http.createServer(app);
const wss = new WebSocketServer({ noServer: true });

// --- WebSocket Connection ---
wss.on("connection", (ws) => {
  console.log("[WebSocket] Client connected");
  const interval = setInterval(async () => {
    try {
      const latest = await store.latestByDevice();
      const actions = await store.listActions(10);
      const now = Date.now() / 1000;
      ws.send(
        JSON.stringify({
          type: "STATE_UPDATE",
          timestamp: now,
          telemetry: latest,
          recent_actions: actions,
          system_status: {
            api: true,
            mqtt_connected: mqttIngestion.connected,
            last_telemetry_at: Math.max(...Object.values(latest).map((x) => x.received_at || 0), 0),
          },
        })
      );
    } catch (err) {
      console.warn("[WebSocket Broadcast Error]:", err.message);
    }
  }, 1500);

  ws.on("close", () => {
    clearInterval(interval);
    console.log("[WebSocket] Client disconnected");
  });
});

server.on("upgrade", (request, socket, head) => {
  const pathname = new URL(request.url, `http://${request.headers.host}`).pathname;
  if (pathname === "/ws/telemetry") {
    wss.handleUpgrade(request, socket, head, (ws) => {
      wss.emit("connection", ws, request);
    });
  } else {
    socket.destroy();
  }
});

// --- REST API Endpoints ---

app.get("/api/health", (req, res) => {
  const status = mqttIngestion.status();
  res.json({
    status: status.connected ? "ok" : "degraded",
    api_status: "online",
    mqtt_configured: status.configured,
    mqtt_connected: status.connected,
    mqtt_subscribed: status.subscribed,
    mqtt_error: status.last_error,
    last_mqtt_message_at: status.last_message_at,
    topic: process.env.MQTT_TOPIC || "hackathon/team_2/test/telemetry",
  });
});

app.get("/api/mqtt/status", (req, res) => {
  res.json(mqttIngestion.status());
});

app.post("/api/telemetry", async (req, res) => {
  try {
    const message = req.body;
    if (!message.device_code || !message.metrics) {
      return res.status(400).json({ error: "device_code and metrics required" });
    }
    const processed = mqttIngestion.processor.process(message);
    await store.ingest(message, "API", processed.quality);

    if (mongoStore && mongoStore.connected) {
      await mongoStore.ingest(processed);
    }

    res.json({ accepted: true, device_code: message.device_code, quality: processed.quality });
  } catch (err) {
    res.status(400).json({ error: err.message });
  }
});

app.post("/api/demo/seed", async (req, res) => {
  const scenario = req.body.scenario || "dry";
  const now = Date.now() / 1000;
  const samplesByScenario = {
    normal: [
      ["SOIL_01", { soil_moisture: 45, temperature: 28 }],
      ["WEATHER_01", { temperature: 29, humidity: 65 }],
      ["PUMP_01", { flow_rate: 18, power: 430, pump_status: 1 }],
      ["PH_01", { ph: 6.4 }],
      ["TANK_01", { level: 72 }],
      ["SUN_01", { lux: 28000 }],
    ],
    dry: [
      ["SOIL_01", { soil_moisture: 18, temperature: 31.2 }],
      ["WEATHER_01", { temperature: 35, humidity: 48 }],
      ["PUMP_01", { flow_rate: 18, power: 430, pump_status: 1 }],
      ["PH_01", { ph: 6.4 }],
      ["TANK_01", { level: 72 }],
      ["SUN_01", { lux: 78000 }],
    ],
    stale: [
      ["SOIL_01", { soil_moisture: 18, temperature: 31.2 }],
      ["WEATHER_01", { temperature: 35, humidity: 48 }],
      ["PUMP_01", { flow_rate: 18, power: 430, pump_status: 1 }],
      ["PH_01", { ph: 6.4 }],
      ["TANK_01", { level: 72 }],
      ["SUN_01", { lux: 78000 }],
    ],
    pump_failure: [
      ["SOIL_01", { soil_moisture: 15, temperature: 31 }],
      ["WEATHER_01", { temperature: 35, humidity: 48 }],
      ["PUMP_01", { flow_rate: 0, power: 0, pump_status: 0 }],
      ["PH_01", { ph: 6.4 }],
      ["TANK_01", { level: 72 }],
      ["SUN_01", { lux: 78000 }],
    ],
  };

  const samples = samplesByScenario[scenario] || samplesByScenario.dry;
  for (const [deviceCode, metrics] of samples) {
    const ts = scenario === "stale" && deviceCode === "SOIL_01" ? now - 1500 : now;
    await store.ingest({ device_code: deviceCode, timestamp: ts, metrics }, "DEMO");
  }

  res.json({ accepted: samples.length, mode: "DEMO", scenario });
});

app.get("/api/telemetry/latest", async (req, res) => {
  const latest = await store.latestByDevice();
  res.json(latest);
});

app.get("/api/telemetry/status", async (req, res) => {
  const latest = await store.latestByDevice();
  const now = Date.now() / 1000;
  const expected = ["SOIL_01", "WEATHER_01", "PUMP_01", "PH_01", "TANK_01", "SUN_01"];
  const staleThreshold = parseInt(process.env.STALE_AFTER_SECONDS || "300", 10);

  const devices = {};
  for (const dev of expected) {
    const reading = latest[dev];
    if (!reading) {
      devices[dev] = { state: "OFFLINE", age_seconds: null, source_type: null, quality: null };
      continue;
    }
    const age = Math.max(0, now - reading.timestamp);
    devices[dev] = {
      state: age <= staleThreshold ? "FRESH" : "STALE",
      age_seconds: Math.round(age * 10) / 10,
      source_type: reading.source_type,
      quality: reading.quality,
    };
  }

  res.json({
    timestamp: now,
    expected_devices: expected.length,
    reporting_devices: Object.keys(latest).length,
    fresh_devices: Object.values(devices).filter((x) => x.state === "FRESH").length,
    mqtt_live_devices: Object.values(devices).filter((x) => x.source_type === "MQTT").length,
    devices,
  });
});

app.get("/api/telemetry/history", async (req, res) => {
  const deviceId = req.query.device_id;
  const limit = parseInt(req.query.limit || "30", 10);
  const minutes = req.query.minutes ? parseInt(req.query.minutes, 10) : null;
  const points = parseInt(req.query.points || "30", 10);

  if (!deviceId) return res.status(400).json({ error: "device_id query param required" });

  if (minutes) {
    const minTs = Date.now() / 1000 - minutes * 60;
    const history = await store.telemetryHistoryWindow(deviceId, minTs, points);
    return res.json(history);
  }

  const history = await store.telemetryHistory(deviceId, limit);
  res.json(history);
});

app.get("/api/telemetry/snapshot", async (req, res) => {
  const latest = await store.latestByDevice();
  const required = ["SOIL_01", "WEATHER_01", "PUMP_01", "PH_01", "TANK_01", "SUN_01"];
  const now = Date.now() / 1000;
  const staleThreshold = parseInt(process.env.STALE_AFTER_SECONDS || "300", 10);

  const issues = [];
  const snapshot = {};
  for (const dev of required) {
    const item = latest[dev];
    if (!item) {
      issues.push(`MISSING_REQUIRED_METRICS:${dev}`);
      continue;
    }
    if (now - item.timestamp > staleThreshold) {
      issues.push(`STALE_DATA:${dev}`);
    }
    snapshot[dev] = item;
  }

  const sourceType = Object.values(snapshot).some((x) => x.source_type === "MQTT") ? "MQTT" : "DEMO";
  res.json({
    source_type: sourceType,
    topic: process.env.MQTT_TOPIC || "hackathon/team_2/test/telemetry",
    snapshot_at: now,
    telemetry: snapshot,
    ready_for_ai: issues.length === 0,
    issues,
  });
});

app.get("/api/agents/status", async (req, res) => {
  try {
    const result = await coordinator.handle("Ktra trạng thái AI Agents", "System Monitor");
    res.json({
      status: "success",
      agent_health: result.agent_health,
      agent_dialogue: result.agent_dialogue,
      ai_executive_summary: result.ai_executive_summary,
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.post("/api/coordinate", async (req, res) => {
  const settings = getSettings();
  const requestText = req.body.request || settings.default_prompt;
  const managerName = req.body.manager_name || settings.manager_name;
  const result = await coordinator.handle(requestText, managerName);
  res.json(result);
});

app.post("/api/dialogue/summary", async (req, res) => {
  const settings = getSettings();
  const requestText = req.body.request || settings.default_prompt;
  const managerName = req.body.manager_name || settings.manager_name;
  const result = await coordinator.handle(requestText, managerName);
  const narrative = coordinator.summarizeDialogue(result);
  const actionInfo = result.agent_trace?.[3] || {};

  res.json({
    status: "success",
    manager_request: requestText,
    manager_name: managerName,
    narrative_summary: narrative,
    action_type: actionInfo.created?.action_type,
    verification_status: actionInfo.verification?.status,
    agent_health: result.agent_health,
    agent_dialogue: result.agent_dialogue || [],
    ai_executive_summary: result.ai_executive_summary,
  });
});

app.get("/api/dialogue/summary", async (req, res) => {
  const result = await coordinator.handle("Hãy kiểm tra và lập kế hoạch tưới hôm nay", "Quản lý Trang trại A");
  const narrative = coordinator.summarizeDialogue(result);
  res.json({
    status: "success",
    narrative_summary: narrative,
    agent_health: result.agent_health,
    agent_dialogue: result.agent_dialogue || [],
    ai_executive_summary: result.ai_executive_summary,
  });
});

app.post("/api/coordination-runs", async (req, res) => {
  const { scenario_text, selected_agents, target_zone } = req.body;
  if (!scenario_text || !selected_agents || selected_agents.length < 3) {
    return res.status(400).json({ error: "scenario_text and minimum 3 selected_agents required" });
  }

  const runId = await store.createRun(req.body);
  const rulesResult = await coordinator.handle(scenario_text, "Farm Operator");
  const createdAction = rulesResult.agent_trace[3]?.created;

  const result = {
    run_id: runId,
    status: "COMPLETED",
    scenario_text,
    target_zone: target_zone || "FARM_ZONE_1",
    telemetry_source: { source_type: "API", snapshot_at: Date.now() / 1000 },
    ai_summary: rulesResult.ai_executive_summary || rulesResult.summary,
    real_agent_trace: rulesResult.agent_trace,
    rule_trace: rulesResult.agent_trace,
    decision: createdAction,
    verification_status: "PENDING",
  };

  await store.completeRun(runId, "COMPLETED", result);
  res.json(result);
});

app.get("/api/coordination-runs/:id", async (req, res) => {
  const run = await store.getRun(req.params.id);
  if (!run) return res.status(404).json({ error: "Run not found" });
  res.json(run);
});

app.get("/api/actions", async (req, res) => {
  const limit = parseInt(req.query.limit || "30", 10);
  const actions = await store.listActions(limit);
  res.json(actions);
});

app.get("/api/actions/:id", async (req, res) => {
  const action = await store.getAction(req.params.id);
  if (!action) return res.status(404).json({ error: "Action not found" });
  res.json(action);
});

app.delete("/api/actions", async (req, res) => {
  await store.clearActions();
  res.json({ status: "SUCCESS", message: "Cleared all action history." });
});

app.get("/api/settings", (req, res) => {
  res.json({
    settings: getSettings(),
    llm_slots: getLlmSlots(),
    model_catalog: getModelCatalog(),
    mqtt: mqttIngestion.status(),
    mongo_connected: Boolean(mongoStore?.connected),
  });
});

app.put("/api/settings", (req, res) => {
  const allowed = (({ manager_name, default_prompt, target_zone, stale_after_seconds, enabled_agents, models, gpt_oss_base_url }) => ({
    manager_name,
    default_prompt,
    target_zone,
    stale_after_seconds,
    enabled_agents,
    models,
    gpt_oss_base_url,
  }))(req.body || {});
  const cleaned = Object.fromEntries(Object.entries(allowed).filter(([, v]) => v !== undefined));
  const settings = updateSettings(cleaned);
  res.json({ settings, llm_slots: getLlmSlots(), model_catalog: getModelCatalog() });
});

app.put("/api/settings/llm", (req, res) => {
  const body = req.body || {};
  if (body.models || body.gpt_oss_base_url) {
    updateSettings({
      models: body.models,
      gpt_oss_base_url: body.gpt_oss_base_url,
    });
  }
  if (body.keys) {
    updateSecrets(body.keys);
  }
  res.json({
    settings: getSettings(),
    llm_slots: getLlmSlots(),
    model_catalog: getModelCatalog(),
    saved: true,
  });
});

app.get("/api/farm-map", (req, res) => {
  res.json(getFarmMap());
});

app.put("/api/farm-map", (req, res) => {
  const map = saveFarmMap(req.body || {});
  res.json(map);
});

app.get("/api/overview", async (req, res) => {
  const latest = await store.latestByDevice();
  const actions = await store.listActions(5);
  const settings = getSettings();
  const now = Date.now() / 1000;
  const staleAfter = settings.stale_after_seconds;
  const soil = latest.SOIL_01?.metrics?.soil_moisture;
  const pending = actions.filter((a) => a.status === "PENDING_APPROVAL").length;

  let verdict = "ỔN ĐỊNH";
  let detail = "Các chỉ số chính trong ngưỡng vận hành.";
  if (soil !== undefined && soil < 35) {
    verdict = "CẦN TƯỚI";
    detail = `Độ ẩm đất ${soil}% — dưới ngưỡng tham chiếu 35%.`;
  } else if (!latest.SOIL_01 || now - (latest.SOIL_01.timestamp || 0) > staleAfter) {
    verdict = "THIẾU DỮ LIỆU";
    detail = "Cảm biến đất chưa có dữ liệu mới. Kiểm tra MQTT hoặc nạp demo.";
  } else if ((latest.TANK_01?.metrics?.level ?? 100) < 30) {
    verdict = "THIẾU NƯỚC";
    detail = "Bồn nước dưới mức tối thiểu 30%.";
  }

  res.json({
    verdict,
    detail,
    pending_approvals: pending,
    telemetry: latest,
    recent_actions: actions,
    settings,
    system: {
      api: true,
      mqtt_connected: mqttIngestion.connected,
      mongo_connected: Boolean(mongoStore?.connected),
    },
  });
});

app.patch("/api/actions/:id/approval", async (req, res) => {
  const { decision, operator_note } = req.body;
  const action = await store.getAction(req.params.id);
  if (!action) return res.status(404).json({ error: "Action not found" });
  if (action.status !== "PENDING_APPROVAL") {
    return res.status(409).json({ code: "INVALID_ACTION_STATE", status: action.status });
  }
  const status = decision === "APPROVE" ? "APPROVED" : "REJECTED";
  const updated = await store.updateAction(req.params.id, status, {
    operator_note: operator_note || "",
    operator_decision_at: Date.now() / 1000,
  });
  res.json(updated);
});

app.post("/api/actions/:id/verify", async (req, res) => {
  const action = await store.getAction(req.params.id);
  if (!action) return res.status(404).json({ error: "Action not found" });
  if (!["APPROVED", "EXECUTING"].includes(action.status)) {
    return res.status(409).json({ code: "ACTION_NOT_EXECUTING", status: action.status });
  }
  const pump = await store.latestAfter("PUMP_01", action.created_at);
  if (!pump || pump.source_type !== "MQTT" || (pump.metrics?.flow_rate || 0) <= 0) {
    return res.json({
      action,
      verification_status: "PENDING",
      reason: "No new PUMP_01 telemetry proves execution.",
    });
  }
  const verified = await store.updateAction(req.params.id, "VERIFIED", {
    verification_evidence: pump,
    verified_at: Date.now() / 1000,
  });
  res.json({ action: verified || action, verification_status: "VERIFIED" });
});

// --- React production build (client/dist) ---
const clientBuildPath = path.join(__dirname, "../client/dist");
app.use(express.static(clientBuildPath));
app.get("*", (req, res) => {
  if (req.path.startsWith("/api") || req.path.startsWith("/ws")) {
    return res.status(404).json({ error: "Endpoint not found" });
  }
  res.sendFile(path.join(clientBuildPath, "index.html"), (err) => {
    if (err) {
      res.status(503).type("html").send(`
        <!DOCTYPE html>
        <html lang="vi">
        <head><meta charset="utf-8"><title>FarmOps AI</title></head>
        <body style="font-family:sans-serif;padding:2rem;text-align:center;background:#090d16;color:#f8fafc;">
          <h1>FarmOps AI API đang chạy</h1>
          <p>Chưa có React build. Chạy <code>npm run build</code> rồi khởi động lại server.</p>
          <p>Dev mode: <code>npm run dev</code> → http://127.0.0.1:5173</p>
        </body>
        </html>
      `);
    }
  });
});

server.listen(PORT, HOST, () => {
  console.log(`====================================================`);
  console.log(`🌾 FarmOps AI Node.js Backend Server running on http://${HOST}:${PORT}`);
  console.log(`====================================================`);
});
