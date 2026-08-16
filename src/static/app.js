const knownDevices = ["SOIL_01", "WEATHER_01", "PUMP_01", "PH_01", "TANK_01", "SUN_01"];
const SENSOR_TIMEOUT_SECONDS = 60;
let agentConfigs = [];
let latestTelemetry = {};
let latestActions = [];
let latestHealth = {};

async function api(path, options = {}) {
  const response = await fetch(path, {headers: {"content-type": "application/json", ...(options.headers || {})}, ...options});
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw body.detail || body || {code: "REQUEST_FAILED"};
  return body;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
}

function formatTime(epoch) {
  return epoch ? new Date(epoch * 1000).toLocaleString("vi-VN", {dateStyle: "medium", timeStyle: "medium"}) : "-";
}

function metricLines(metrics) {
  const labels = {soil_moisture:"Độ ẩm đất", soil_temperature:"Nhiệt độ đất", temperature:"Nhiệt độ", humidity:"Độ ẩm không khí", flow_rate:"Lưu lượng bơm", power:"Công suất", ph:"Độ pH", level:"Mực nước bồn", tank_level:"Mực nước bồn", lux:"Cường độ sáng", pump_status:"Trạng thái bơm"};
  const units = {soil_moisture:"%", soil_temperature:"°C", temperature:"°C", humidity:"%", flow_rate:" L/min", power:" W", level:"%", tank_level:"%", lux:" lux"};
  return Object.entries(metrics).map(([key,value]) => `<div class="metric"><small>${labels[key] || escapeHtml(key.replaceAll("_", " "))}</small><b>${key === "pump_status" ? (Number(value) > 0 ? "Sẵn sàng" : "Có lỗi") : `${escapeHtml(value)}${units[key] || ""}`}</b></div>`).join("");
}

function statusVi(status) {
  const labels = {READY:"SẴN SÀNG", NOT_CONFIGURED:"CHƯA CẤU HÌNH", FAILED:"THẤT BẠI", PENDING:"ĐANG CHỜ", PENDING_APPROVAL:"CHỜ PHÊ DUYỆT", APPROVED:"ĐÃ PHÊ DUYỆT", REJECTED:"ĐÃ TỪ CHỐI", CREATED:"ĐÃ TẠO", EXECUTING:"ĐANG THỰC HIỆN", VERIFIED:"ĐÃ XÁC MINH", ACTIVE:"ĐANG HOẠT ĐỘNG", DEGRADED:"SUY GIẢM"};
  return labels[status] || String(status || "-").replaceAll("_", " ");
}

function actionTypeVi(type) {
  const labels = {IRRIGATION_PLAN:"Kế hoạch tưới", FIELD_TASK:"Nhiệm vụ hiện trường", ALERT:"Cảnh báo", NOTIFICATION:"Thông báo"};
  return labels[type] || String(type || "Không tạo hành động").replaceAll("_", " ");
}

function agentNameVi(name) {
  const labels = {"Field IoT Agent":"Tác tử IoT hiện trường", "Irrigation Planning Agent":"Tác tử lập kế hoạch tưới", "Resource Agent":"Tác tử tài nguyên", "Farm Action Agent":"Tác tử hành động nông trại", "Farm Coordinator Agent":"Tác tử điều phối nông trại", "Rule Agent":"Tác tử luật"};
  return labels[name] || name;
}

function setRunStatus(message, kind = "warn") {
  const target = document.querySelector("#run-status");
  target.className = `status ${kind}`;
  target.textContent = message;
}

async function loadHealth() {
  const health = await api("/api/health");
  latestHealth = health;
  const target = document.querySelector("#health");
  target.textContent = health.mqtt_configured ? `MQTT đã cấu hình · ${health.topic}` : "MQTT chưa được cấu hình";
  target.className = `tag ${health.mqtt_configured ? "ok" : "warn"}`;
  renderExecutiveSummary();
}

function renderExecutiveSummary() {
  const coverageTarget = document.querySelector("#kpi-coverage");
  if (!coverageTarget) return;
  const now = Date.now() / 1000;
  const records = knownDevices.map(id => ({id, item: latestTelemetry[id]}));
  const reporting = records.filter(record => record.item).length;
  const fresh = records.filter(record => record.item && now - record.item.timestamp <= SENSOR_TIMEOUT_SECONDS).length;
  const attention = records.filter(record => {
    const state = sensorState(record.id);
    return state.violated || state.freshness !== "fresh";
  }).length;
  const pending = latestActions.filter(action => action.status === "PENDING_APPROVAL").length;
  const sources = new Set(records.filter(record => record.item).map(record => record.item.source_type));
  const isLiveMqtt = sources.has("MQTT");

  coverageTarget.textContent = `${reporting}/6`;
  document.querySelector("#kpi-coverage-note").textContent = reporting === 6 ? "đủ 6 thiết bị đang báo dữ liệu" : `thiếu ${6 - reporting} thiết bị`;
  document.querySelector("#kpi-freshness").textContent = reporting ? `${Math.round(fresh / reporting * 100)}%` : "0%";
  document.querySelector("#kpi-freshness-note").textContent = `${fresh} mới · ${Math.max(0, reporting - fresh)} quá hạn`;
  document.querySelector("#kpi-attention").textContent = String(attention);
  document.querySelector("#kpi-attention-note").textContent = attention ? "cần kiểm tra" : "không có bất thường";
  document.querySelector("#kpi-approvals").textContent = String(pending);
  document.querySelector("#snapshot-updated").textContent = reporting ? `Cập nhật lúc ${new Date().toLocaleTimeString("vi-VN")}` : "Đang chờ dữ liệu cảm biến";

  const message = document.querySelector("#executive-message");
  if (!latestHealth.mqtt_configured) {
    message.className = "executive-message bad";
    message.textContent = "Luồng quyết định chưa khả dụng vì MQTT chưa được cấu hình.";
  } else if (!isLiveMqtt && reporting) {
    message.className = "executive-message warn";
    message.textContent = "Đang hiển thị dữ liệu mẫu hoặc API. Quyết định AI trực tiếp bị khóa cho tới khi có bằng chứng MQTT còn mới.";
  } else if (attention) {
    message.className = "executive-message warn";
    message.textContent = `${attention} tín hiệu cảm biến cần được kiểm tra trước khi phê duyệt quyết định vận hành.`;
  } else if (reporting === 6 && isLiveMqtt) {
    message.className = "executive-message ok";
    message.textContent = "Tất cả hệ thống được giám sát đang báo dữ liệu bình thường với bằng chứng MQTT trực tiếp.";
  } else {
    message.className = "executive-message muted";
    message.textContent = "Đang kết nối dữ liệu vận hành...";
  }
}

async function loadTelemetry() {
  const data = await api("/api/telemetry/latest");
  latestTelemetry = data;
  document.querySelector("#devices").innerHTML = knownDevices.map(device => {
    const item = data[device];
    if (!item) return `<article class="device missing"><div class="device-title"><span class="device-icon">—</span><div><b>${device}</b><br><small>Chưa nhận dữ liệu cảm biến</small></div></div><div class="meter"><i style="width:8%"></i></div><div class="metrics"><span class="bad">THIẾU DỮ LIỆU</span></div><div class="evidence">Đang chờ dữ liệu</div></article>`;
    const age = Math.max(0, Math.round(Date.now() / 1000 - item.timestamp));
    const freshness = age <= SENSOR_TIMEOUT_SECONDS ? "FRESH" : "OFFLINE";
    const source = item.source_type || "API";
    const strength = Math.max(8, Math.min(100, Number(item.metrics.soil_moisture ?? item.metrics.level ?? item.metrics.humidity ?? item.metrics.flow_rate ?? 55)));
    return `<article class="device ${freshness === "FRESH" ? "fresh" : "missing"}"><div class="device-title"><span class="device-icon">●</span><div><b>${device === "PUMP_01" ? "PUMP_1" : device}</b><br><small>${source}${source === "MQTT" ? " · TRỰC TIẾP" : ""}</small></div></div><div class="meter"><i style="width:${strength}%"></i></div><div class="metrics">${metricLines(item.metrics)}</div><div class="evidence"><span class="${freshness === "FRESH" ? "ok" : "bad"}">${freshness === "FRESH" ? "DỮ LIỆU MỚI" : "MẤT KẾT NỐI"}</span><br>${age} giây trước<br>${formatTime(item.timestamp)}</div></article>`;
  }).join("");
  renderFarmMap();
  renderExecutiveSummary();
  drawSensorChart().catch(() => {});
}

async function drawSensorChart() {
  const specs = [
    {device:"SOIL_01", metric:"soil_moisture", name:"Soil Moisture", unit:"%", axis:"Moisture (%)", color:"#5be2ad", domain:[0,100], decimals:1},
    {device:"WEATHER_01", metric:"temperature", name:"Temperature", unit:"°C", axis:"Temperature (°C)", color:"#78c8ff", decimals:1},
    {device:"PUMP_01", metric:"flow_rate", name:"Pump Flow", unit:" L/min", axis:"Flow (L/min)", color:"#ffc46b", zeroBased:true, decimals:1},
    {device:"PH_01", metric:"ph", name:"Soil pH", unit:"", axis:"pH", color:"#e99cff", domain:[0,14], decimals:1},
    {device:"TANK_01", metric:"level", name:"Tank Level", unit:"%", axis:"Level (%)", color:"#ff8791", domain:[0,100], decimals:1},
    {device:"SUN_01", metric:"lux", name:"Light Intensity", unit:" lux", axis:"Illuminance (lux)", color:"#f6e05e", zeroBased:true, decimals:0},
  ];
  const histories = await Promise.all(specs.map(spec => api(`/api/telemetry/history?device_id=${spec.device}&minutes=30&points=30`).catch(() => [])));
  const now = Date.now() / 1000;
  const windowStart = now - 30 * 60;
  const target = document.querySelector("#sensor-trends");
  target.innerHTML = specs.map((spec, index) => renderMiniChart(spec, histories[index], windowStart, now)).join("");
  bindChartTooltips();
}

function renderMiniChart(spec, history, windowStart, now) {
  const samples = history
    .map(row => ({timestamp:Number(row.timestamp), value:Number(row.metrics?.[spec.metric])}))
    .filter(sample => Number.isFinite(sample.timestamp) && Number.isFinite(sample.value) && sample.timestamp >= windowStart)
    .sort((a,b) => a.timestamp - b.timestamp);
  const liveValue = Number(latestTelemetry[spec.device]?.metrics?.[spec.metric]);
  const currentValue = Number.isFinite(liveValue) ? liveValue : samples.at(-1)?.value;
  const currentLabel = Number.isFinite(currentValue) ? `${formatChartValue(currentValue, spec)}${spec.unit}` : "—";
  const header = `<div class="mini-chart-head"><span class="mini-chart-id">${spec.device}</span><strong class="mini-chart-value">${currentLabel}</strong><span class="mini-chart-name">${spec.name}</span></div>`;
  if (!samples.length) return `<article class="mini-chart">${header}<div class="chart-empty">Waiting for historical telemetry</div></article>`;

  const values = samples.map(sample => sample.value);
  const [domainMin, domainMax] = chartDomain(spec, values);
  const width = 380, height = 190, left = 54, right = 368, top = 17, bottom = 145;
  const x = timestamp => left + ((Math.min(now, Math.max(windowStart, timestamp)) - windowStart) / (now - windowStart)) * (right - left);
  const y = value => bottom - ((value - domainMin) / (domainMax - domainMin)) * (bottom - top);
  const points = samples.map(sample => `${x(sample.timestamp).toFixed(1)},${y(sample.value).toFixed(1)}`).join(" ");
  const yTicks = [domainMax, (domainMin + domainMax) / 2, domainMin];
  const grid = yTicks.map((tick, tickIndex) => { const py = top + tickIndex * ((bottom - top) / 2); return `<line class="mini-chart-grid" x1="${left}" y1="${py}" x2="${right}" y2="${py}"/><text class="mini-chart-axis" x="${left-7}" y="${py+3}" text-anchor="end">${formatAxisValue(tick, spec)}</text>`; }).join("");
  const timeTicks = [windowStart, windowStart + 15 * 60, now];
  const timeLabels = timeTicks.map((timestamp, tickIndex) => `<text class="mini-chart-axis" x="${x(timestamp)}" y="169" text-anchor="${tickIndex === 0 ? "start" : tickIndex === 2 ? "end" : "middle"}">${tickIndex === 2 ? "Now" : formatChartTime(timestamp)}</text>`).join("");
  const circles = samples.map(sample => `<circle class="chart-point" tabindex="0" cx="${x(sample.timestamp).toFixed(1)}" cy="${y(sample.value).toFixed(1)}" r="2.6" fill="${spec.color}" data-chart-point data-time="${sample.timestamp}" data-value="${sample.value}" data-name="${spec.name}" data-unit="${escapeHtml(spec.unit)}" data-decimals="${spec.decimals}" aria-label="${spec.name}, ${formatChartValue(sample.value, spec)}${spec.unit}, ${formatChartTime(sample.timestamp)}"/>`).join("");
  return `<article class="mini-chart">${header}<svg class="mini-chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${spec.name} readings during the last 30 minutes"><text class="mini-chart-axis" transform="translate(10 82) rotate(-90)" text-anchor="middle">${spec.axis}</text>${grid}<polyline class="mini-chart-line" points="${points}" stroke="${spec.color}"/>${circles}${timeLabels}</svg><div class="chart-tooltip" role="tooltip"></div></article>`;
}

function chartDomain(spec, values) {
  if (spec.domain) return spec.domain;
  const min = Math.min(...values), max = Math.max(...values);
  if (spec.zeroBased) return [0, Math.max(1, max * 1.15)];
  const padding = Math.max((max - min) * .18, 1);
  return [min - padding, max + padding];
}

function formatChartValue(value, spec) {
  return Number(value).toLocaleString("en-US", {minimumFractionDigits:spec.decimals, maximumFractionDigits:spec.decimals});
}

function formatAxisValue(value, spec) {
  const decimals = spec.metric === "ph" ? 1 : Math.abs(value) >= 1000 ? 0 : Math.abs(value) < 10 ? 1 : 0;
  return Number(value).toLocaleString("en-US", {maximumFractionDigits:decimals});
}

function formatChartTime(epoch) {
  return new Date(epoch * 1000).toLocaleTimeString("en-US", {hour:"2-digit", minute:"2-digit"});
}

function bindChartTooltips() {
  document.querySelectorAll("[data-chart-point]").forEach(point => {
    const chart = point.closest(".mini-chart");
    const tooltip = chart.querySelector(".chart-tooltip");
    const show = event => {
      const rect = chart.getBoundingClientRect();
      const pointRect = point.getBoundingClientRect();
      const pointerX = event.clientX || pointRect.left + pointRect.width / 2;
      const pointerY = event.clientY || pointRect.top + pointRect.height / 2;
      tooltip.style.left = `${Math.max(76, Math.min(rect.width - 76, pointerX - rect.left))}px`;
      tooltip.style.top = `${Math.max(68, pointerY - rect.top)}px`;
      const value = Number(point.dataset.value).toLocaleString("en-US", {minimumFractionDigits:Number(point.dataset.decimals), maximumFractionDigits:Number(point.dataset.decimals)});
      tooltip.innerHTML = `<span class="chart-tooltip-time">${new Date(Number(point.dataset.time) * 1000).toLocaleTimeString("en-US", {hour:"numeric", minute:"2-digit"})}</span><b>${point.dataset.name}: ${value}${point.dataset.unit}</b>`;
      tooltip.classList.add("visible");
    };
    point.addEventListener("pointerenter", show);
    point.addEventListener("pointermove", show);
    point.addEventListener("focus", show);
    point.addEventListener("pointerleave", () => tooltip.classList.remove("visible"));
    point.addEventListener("blur", () => tooltip.classList.remove("visible"));
  });
}

function sensorState(deviceId) {
  const item = latestTelemetry[deviceId];
  if (!item) return {freshness:"offline", violated:false};
  const age = Math.max(0, Date.now()/1000 - item.timestamp);
  const freshness = age > SENSOR_TIMEOUT_SECONDS ? "offline" : "fresh";
  const m = item.metrics || {};
  const violated = freshness === "fresh" && (deviceId === "SOIL_01" ? Number(m.soil_moisture) < 30 : deviceId === "TANK_01" ? Number(m.tank_level ?? m.level) < 20 : deviceId === "PUMP_01" ? String(m.pump_status).toUpperCase() === "ERROR" || Number(m.pump_status) === 0 : deviceId === "PH_01" ? Number(m.ph) < 5.5 || Number(m.ph) > 7.5 : false);
  return {freshness, violated};
}

function worstZoneStatus(ids) {
  const states = ids.map(sensorState);
  if (states.some(s=>s.freshness === "offline")) return "offline";
  return "normal";
}

function renderFarmMap(selectedId = null) {
  const svg = document.querySelector("#farm-map"); if (!svg) return;
  const styles = {critical:{fill:"#3b1212",stroke:"#e24b4a",label:"CRITICAL"},stale:{fill:"#2d2200",stroke:"#ba7517",label:"STALE"},offline:{fill:"#2f1518",stroke:"#ff7c86",label:"OFFLINE"},normal:{fill:"#0d2620",stroke:"#1d9e75",label:"NORMAL"}};
  const ids = ["SOIL_01","WEATHER_01","PUMP_01","PH_01","TANK_01","SUN_01"];
  const labels = {SOIL_01:"SOIL_01",WEATHER_01:"WEATHER_01",PUMP_01:"PUMP_1",PH_01:"PH_01",TANK_01:"TANK_01",SUN_01:"SUN_01"};
  const roles = {SOIL_01:"Soil",WEATHER_01:"Weather",PUMP_01:"Pump",PH_01:"Acidity",TANK_01:"Water tank",SUN_01:"Light"};
  const positions = {SOIL_01:[155,155],WEATHER_01:[430,155],PUMP_01:[705,155],PH_01:[155,290],TANK_01:[430,290],SUN_01:[705,290]};
  const style = styles[worstZoneStatus(ids)];
  const zoneSvg = `<g><rect x="20" y="24" width="820" height="372" rx="22" fill="${style.fill}" stroke="${style.stroke}" stroke-width="2"/><text x="46" y="58" fill="${style.stroke}" font-size="17" font-weight="700">Farm Zone 1</text><text x="46" y="79" fill="#9db5aa" font-size="11">6 connected sensor positions</text><rect x="720" y="42" width="92" height="27" rx="14" fill="${style.stroke}"/><text x="766" y="60" text-anchor="middle" fill="#fff" font-size="11" font-weight="800">${style.label}</text><path d="M52 100 H808 M292 108 V365 M568 108 V365 M52 230 H808" stroke="#315348" stroke-width="1" stroke-dasharray="5 7" opacity=".55"/></g>`;
  const pinSvg = Object.entries(positions).map(([id,[x,y]])=>{const state=sensorState(id);const color=state.freshness==="offline"?"#ff7c86":"#1d9e75";return `<g class="sensor-node" data-sensor="${id}" style="cursor:pointer"><rect class="sensor-card" x="${x-108}" y="${y-43}" width="216" height="86" rx="15" fill="#102b23" stroke="${state.freshness === "offline" ? "#ff7c86" : "#315348"}"/><circle cx="${x-75}" cy="${y}" r="16" fill="${color}" stroke="#effffb" stroke-width="2"/><text x="${x-48}" y="${y-5}" fill="#effffb" font-size="14" font-weight="700">${labels[id]}</text><text x="${x-48}" y="${y+15}" fill="${state.freshness === "offline" ? "#ff9ca4" : "#9db5aa"}" font-size="11">${roles[id]} · ${state.freshness.toUpperCase()}</text></g>`}).join("");
  let popup = "";
  if (selectedId && positions[selectedId]) { const [x,y]=positions[selectedId]; const item=latestTelemetry[selectedId]; const state=sensorState(selectedId); const px=Math.max(30,Math.min(580,x>560?x-270:x+30)), py=Math.max(88,Math.min(205,y>230?y-180:y-58)); const age=item?Math.max(0,Math.round(Date.now()/1000-item.timestamp)):null; const ageLabel=age===null?"No data received":age<=1?"Updated just now":`Updated ${age} seconds ago`; popup=`<foreignObject class="sensor-popup" x="${px}" y="${py}" width="250" height="190"><div xmlns="http://www.w3.org/1999/xhtml" style="background:#0d292f;border:1px solid #315348;border-radius:13px;padding:12px;color:#effffb;font:12px Segoe UI,Arial;box-shadow:0 12px 28px rgba(0,0,0,.35)"><div style="display:flex;justify-content:space-between;align-items:center"><b style="font-size:14px">${labels[selectedId]}</b><span style="color:${state.freshness==='fresh'?'#5be2ad':'#ff9ca4'};font-weight:700">${state.freshness.toUpperCase()}</span></div><hr style="border:0;border-top:1px solid #315348;margin:8px 0"/><div class="metrics">${item?metricLines(item.metrics):'<span>Offline — no data</span>'}</div><div style="color:#9db5aa;margin-top:8px">${ageLabel}</div><button data-history="${selectedId}" style="margin-top:8px;padding:5px 9px">View history</button></div></foreignObject>`; }
  if (!Object.keys(latestTelemetry).length) popup += `<text x="430" y="205" text-anchor="middle" fill="#a0c1bf" font-size="18">No telemetry available</text>`;
  svg.innerHTML = zoneSvg + pinSvg + popup;
  svg.querySelectorAll("[data-sensor]").forEach(pin=>pin.addEventListener("click",event=>{event.stopPropagation();renderFarmMap(pin.dataset.sensor)}));
  svg.querySelector("[data-history]")?.addEventListener("click",event=>{event.stopPropagation();showMapHistory(event.target.dataset.history)});
  svg.onclick = event => { if (!event.target.closest(".sensor-node") && !event.target.closest(".sensor-popup")) renderFarmMap(); };
}

async function showMapHistory(deviceId) {
  const history = await api(`/api/telemetry/history?device_id=${deviceId}&limit=5`);
  const target = document.querySelector("#map-history");
  const displayId = deviceId === "PUMP_01" ? "PUMP_1" : deviceId;
  target.innerHTML = `<div class="eyebrow">Sensor history</div><h2>${displayId}</h2><p class="muted">Latest five records</p>${history.length?history.map(row=>`<div class="history-row"><span>${formatTime(row.timestamp)}</span><span class="tag">${row.source_type}</span><span>${Object.entries(row.metrics).map(([k,v])=>`${escapeHtml(k.replaceAll("_", " "))}: ${escapeHtml(v)}`).join(" · ")}</span></div>`).join(""):"<p>No historical records available.</p>"}`;
}

async function loadSnapshot() {
  const snapshot = await api("/api/telemetry/snapshot");
  const target = document.querySelector("#snapshot-summary");
  if (!target) return;
  if (snapshot.ready_for_ai) {
    target.innerHTML = `<span class="ok">READY: Required live MQTT data is available.</span> Topic: <code>${escapeHtml(snapshot.topic)}</code>`;
  } else {
    target.innerHTML = `<span class="warn">LIVE AI IS NOT READY:</span> ${snapshot.issues.map(escapeHtml).join(" · ")}`;
  }
}

function renderAgentSelector() {
  document.querySelector("#agent-selector").innerHTML = agentConfigs.map(agent => `<label class="agent"><input type="checkbox" value="${agent.agent_id}" ${agent.enabled && agent.connection_status === "READY" ? "checked" : ""}> <b>${escapeHtml(agent.display_name)}</b><br><small>${escapeHtml(agent.role)}</small><p><span class="${agent.connection_status === "READY" ? "ok" : "warn"}">${agent.connection_status}</span> · ${escapeHtml(agent.provider)}/${escapeHtml(agent.model)}</p></label>`).join("");
  const updateSummary = () => {
    const selected = [...document.querySelectorAll("#agent-selector input:checked")].map(input => agentConfigs.find(agent => agent.agent_id === input.value)?.display_name).filter(Boolean);
    const target = document.querySelector("#ai-selection-summary");
    if (target) target.textContent = selected.length ? `Selected AI: ${selected.join(" · ")}` : "No AI provider selected. Open AI Settings to choose providers.";
  };
  document.querySelectorAll("#agent-selector input").forEach(input => input.addEventListener("change", updateSummary));
  updateSummary();
}

function renderAgentConfigs() {
  document.querySelector("#agent-configs").innerHTML = agentConfigs.map(agent => `<article class="agent" data-agent="${agent.agent_id}"><div class="section-head"><div><b>${escapeHtml(agent.display_name)}</b><p class="muted">${escapeHtml(agent.role)}</p></div><span class="tag ${agent.connection_status === "READY" ? "ok" : "warn"}">${agent.connection_status}</span></div><div class="two"><label>Provider<select class="provider"><option value="openai" ${agent.provider === "openai" ? "selected" : ""}>ChatGPT / OpenAI</option><option value="gemini" ${agent.provider === "gemini" ? "selected" : ""}>Google Gemini</option><option value="anthropic" ${agent.provider === "anthropic" ? "selected" : ""}>Claude / Anthropic</option><option value="deepseek" ${agent.provider === "deepseek" ? "selected" : ""}>DeepSeek</option></select></label><label>Model<input class="model" value="${escapeHtml(agent.model)}" maxlength="120"></label></div><label>API key<input class="api-key" type="password" autocomplete="new-password" placeholder="Enter a new or replacement API key"></label><label><input class="enabled" type="checkbox" ${agent.enabled ? "checked" : ""}> Enable this provider</label><div class="row"><button class="save-agent secondary">Save settings</button><button class="test-agent">Test connection</button></div><span class="agent-message evidence">${agent.has_api_key ? "Key stored securely in the backend" : "No API key configured"}${agent.last_error ? ` · ${escapeHtml(agent.last_error)}` : ""}</span></article>`).join("");
  document.querySelectorAll(".save-agent").forEach(button => button.addEventListener("click", saveAgent));
  document.querySelectorAll(".test-agent").forEach(button => button.addEventListener("click", testAgent));
}

async function loadAgents() {
  agentConfigs = await api("/api/agents");
  renderAgentSelector();
  renderAgentConfigs();
}

async function saveAgent(event) {
  const card = event.target.closest("[data-agent]");
  const key = card.querySelector(".api-key").value.trim();
  const message = card.querySelector(".agent-message");
  if (!key) { message.textContent = "Enter an API key to save or update this provider. Stored keys cannot be read back."; return; }
  event.target.disabled = true;
  try {
    await api(`/api/agents/${card.dataset.agent}/config`, {method: "PUT", body: JSON.stringify({provider: card.querySelector(".provider").value, model: card.querySelector(".model").value.trim(), api_key: key, enabled: card.querySelector(".enabled").checked})});
    message.textContent = "Saved securely in the backend. Test the connection to mark this provider ready.";
    card.querySelector(".api-key").value = "";
    await loadAgents();
  } catch (error) { message.textContent = `Unable to save: ${JSON.stringify(error)}`; }
  finally { event.target.disabled = false; }
}

async function testAgent(event) {
  const card = event.target.closest("[data-agent]");
  const message = card.querySelector(".agent-message");
  event.target.disabled = true; message.textContent = "Connecting to the live provider...";
  try { await api(`/api/agents/${card.dataset.agent}/test-connection`, {method: "POST"}); message.textContent = "READY — live provider connection succeeded."; }
  catch (error) { message.textContent = `FAILED: ${JSON.stringify(error)}`; }
  finally { event.target.disabled = false; await loadAgents(); }
}

function renderRun(result) {
  const target = document.querySelector("#run-result");
  target.className = "";
  const traces = (result.real_agent_trace || []).map(trace => `<div class="trace"><b>${escapeHtml(trace.agent_id)}</b> <span class="tag">${escapeHtml(trace.provider)}/${escapeHtml(trace.model)}</span><p>${escapeHtml(trace.analysis)}</p></div>`).join("");
  const decision = result.decision || {};
  const rules = (result.rule_trace || []).map(step => `<div class="trace"><b>${escapeHtml(step.agent || "Rule Agent")}</b><p>${escapeHtml(step.reason || step.decision || step.verification?.reason || "Evidence processed.")}</p></div>`).join("");
  target.innerHTML = `<div class="row"><span class="tag">${escapeHtml(result.status)}</span><b>${escapeHtml(decision.action_type || "No action created")}</b><span class="warn">${escapeHtml(result.verification_status || "PENDING")}</span></div><p><b>Scenario:</b> ${escapeHtml(result.scenario_text || "-")}</p><p class="evidence"><b>Evidence source:</b> ${escapeHtml(result.telemetry_source?.source_type || "-")} · ${escapeHtml(result.telemetry_source?.topic || "-")}</p>${traces}${rules}`;
}

async function runCoordination() {
  const selected = [...document.querySelectorAll("#agent-selector input:checked")].map(input => input.value);
  if (selected.length < 3) { setRunStatus("Select at least three READY agents.", "bad"); return; }
  const button = document.querySelector("#run"); button.disabled = true; setRunStatus("Creating an MQTT snapshot and calling live providers...", "warn");
  try {
    const result = await api("/api/coordination-runs", {method: "POST", body: JSON.stringify({scenario_text: document.querySelector("#scenario").value.trim(), selected_agents: selected, target_zone: "FARM_ZONE_1"})});
    renderRun(result); setRunStatus("Complete. The action is waiting for operator approval.", "ok"); await loadActions();
  } catch (error) { setRunStatus(`Unable to run: ${JSON.stringify(error)}`, "bad"); }
  finally { button.disabled = false; }
}

async function loadActions() {
  const actions = await api("/api/actions");
  latestActions = actions;
  renderExecutiveSummary();
  const container = document.querySelector("#actions-list");
  const now = Date.now() / 1000;
  const reporting = knownDevices.filter(device => latestTelemetry[device]);
  const offline = knownDevices.filter(device => !latestTelemetry[device] || now - latestTelemetry[device].timestamp > SENSOR_TIMEOUT_SECONDS);
  const mqttLive = reporting.filter(device => latestTelemetry[device].source_type === "MQTT");
  const pending = actions.filter(action => action.status === "PENDING_APPROVAL");
  const displayDevice = device => device === "PUMP_01" ? "PUMP_1" : device;
  const systemCards = [
    `<article class="action action-system"><div class="section-head"><div class="action-title"><span class="action-icon">PL</span><b>Live Monitoring Plan</b></div><span class="tag ${mqttLive.length === 6 && !offline.length ? "ok" : "warn"}">${mqttLive.length === 6 && !offline.length ? "ACTIVE" : "DEGRADED"}</span></div><p>Continuously monitor all six sensors in Farm Zone 1 with a 60-second reporting deadline.</p><p class="evidence">Evidence: ${mqttLive.length}/6 devices reporting from MQTT · Updated from live telemetry</p></article>`,
    `<article class="action action-system"><div class="section-head"><div class="action-title"><span class="action-icon">TK</span><b>Sensor Inspection Task</b></div><span class="tag ${offline.length ? "bad" : "ok"}">${offline.length ? "ACTION REQUIRED" : "NOT REQUIRED"}</span></div><p>${offline.length ? `Inspect ${offline.map(displayDevice).join(", ")} because no reading was received within 60 seconds.` : "No manual inspection is required. Every sensor reported within the last 60 seconds."}</p><p class="evidence">Evidence: ${reporting.length}/6 sensors available · Timeout rule: 60 seconds</p></article>`,
    `<article class="action action-system"><div class="section-head"><div class="action-title"><span class="action-icon">AP</span><b>Approval Queue</b></div><span class="tag ${pending.length ? "warn" : "ok"}">${pending.length ? `${pending.length} PENDING` : "CLEAR"}</span></div><p>${pending.length ? "AI-generated operational decisions are waiting for a manager decision." : "No critical plan is waiting for approval. New AI actions will appear here with supporting evidence."}</p><p class="evidence">Human approval gate · AI actions cannot self-approve</p></article>`,
  ];
  const actionCards = actions.map(action => `<article class="action"><div class="section-head"><b>${escapeHtml(action.action_type.replaceAll("_", " "))}</b><span class="tag">${escapeHtml(action.status.replaceAll("_", " "))}</span></div><p class="evidence">${escapeHtml(action.id)} · ${formatTime(action.created_at)}</p><p>${escapeHtml(action.payload.reason || action.payload.schedule?.target_zone || "Review supporting evidence in the action record.")}</p>${action.status === "PENDING_APPROVAL" ? `<div class="row"><button data-approval="APPROVE" data-id="${action.id}">Approve</button><button class="danger" data-approval="REJECT" data-id="${action.id}">Reject</button></div>` : ""}${["APPROVED","EXECUTING"].includes(action.status) ? `<button class="secondary" data-verify="${action.id}">Verify actuator telemetry</button>` : ""}</article>`);
  container.innerHTML = [...systemCards, ...actionCards].join("");
  document.querySelectorAll("[data-approval]").forEach(button => button.addEventListener("click", approveAction));
  document.querySelectorAll("[data-verify]").forEach(button => button.addEventListener("click", verifyAction));
}

async function approveAction(event) {
  const note = window.prompt("Operator note (optional):", "") ?? "";
  try { await api(`/api/actions/${event.target.dataset.id}/approval`, {method: "PATCH", body: JSON.stringify({decision: event.target.dataset.approval, operator_note: note})}); await loadActions(); }
  catch (error) { window.alert(`Unable to update the action: ${JSON.stringify(error)}`); }
}

async function verifyAction(event) {
  try { const result = await api(`/api/actions/${event.target.dataset.verify}/verify`, {method: "POST"}); window.alert(result.verification_status === "VERIFIED" ? "Verified with MQTT pump telemetry." : "No new MQTT actuator telemetry is available. The action remains unverified."); await loadActions(); }
  catch (error) { window.alert(`Unable to verify the action: ${JSON.stringify(error)}`); }
}

function activateTab(name) { document.querySelectorAll(".tab").forEach(item => item.classList.toggle("active", item.dataset.tab === name)); document.querySelectorAll("main > .panel").forEach(panel => panel.classList.toggle("active", panel.id === name)); if (name === "map") renderFarmMap(); }
document.querySelectorAll(".tab").forEach(tab => tab.addEventListener("click", () => activateTab(tab.dataset.tab)));
document.querySelector("#run").addEventListener("click", runCoordination);
document.querySelector("#refresh").addEventListener("click", loadTelemetry);
document.querySelector("#refresh-actions").addEventListener("click", loadActions);
document.querySelectorAll(".demo").forEach(button => button.addEventListener("click", async () => { await api("/api/demo/seed", {method: "POST", body: JSON.stringify({scenario: button.dataset.scenario})}); await loadTelemetry(); window.alert(`Demo scenario loaded: ${button.textContent}. Demo data cannot trigger a live MQTT AI decision.`); }));

function connectRealtime() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${location.host}/ws/telemetry`);
  socket.onmessage = () => { loadTelemetry().catch(() => {}); loadSnapshot().catch(() => {}); loadActions().catch(() => {}); };
  socket.onclose = () => setTimeout(connectRealtime, 2000);
}

Promise.all([loadHealth(), loadTelemetry(), loadAgents(), loadActions()]).catch(error => setRunStatus(`Unable to connect to the API: ${JSON.stringify(error)}`, "bad"));
setInterval(() => Promise.all([loadTelemetry(), loadHealth()]).catch(() => {}), 10000);
connectRealtime();
