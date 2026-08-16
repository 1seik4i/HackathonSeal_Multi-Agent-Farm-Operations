const knownDevices = ["SOIL_01", "WEATHER_01", "PUMP_01", "PH_01", "TANK_01", "SUN_01"];
const deviceFriendlyNames = {
  SOIL_01: "SOIL_01 (Độ ẩm đất)",
  WEATHER_01: "WEATHER_01 (Thời tiết)",
  PUMP_01: "PUMP_01 (Máy bơm nước)",
  PH_01: "PH_01 (Độ pH đất)",
  TANK_01: "TANK_01 (Mức bồn chứa)",
  SUN_01: "SUN_01 (Cường độ sáng)"
};
const SENSOR_TIMEOUT_SECONDS = 60;
let agentConfigs = [];
let latestTelemetry = {};
let latestActions = [];
let latestHealth = {};

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "content-type": "application/json", ...(options.headers || {}) }, ...options });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw body.detail || body || { code: "REQUEST_FAILED" };
  return body;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
}

function formatTime(epoch) {
  return epoch ? new Date(epoch * 1000).toLocaleString("vi-VN", { dateStyle: "medium", timeStyle: "medium" }) : "-";
}

function metricLines(metrics) {
  const labels = { soil_moisture: "Độ ẩm đất", soil_temperature: "Nhiệt độ đất", temperature: "Nhiệt độ không khí", humidity: "Độ ẩm không khí", flow_rate: "Lưu lượng dòng chảy", power: "Công suất hoạt động", ph: "Độ pH", level: "Mực nước", tank_level: "Mực nước bồn", lux: "Cường độ ánh sáng", pump_status: "Trạng thái bơm" };
  const units = { soil_moisture: "%", soil_temperature: "°C", temperature: "°C", humidity: "%", flow_rate: " L/min", power: " W", level: "%", tank_level: "%", lux: " lux" };
  return Object.entries(metrics).map(([key, value]) => `<div class="metric"><small>${labels[key] || escapeHtml(key.replaceAll("_", " "))}</small><b>${key === "pump_status" ? (Number(value) > 0 ? "Sẵn sàng" : "Có lỗi/Tắt") : `${escapeHtml(value)}${units[key] || ""}`}</b></div>`).join("");
}

function statusVi(status) {
  const labels = { READY: "SẴN SÀNG", NOT_CONFIGURED: "CHƯA CẤU HÌNH", FAILED: "THẤT BẠI", PENDING: "ĐANG CHỜ", PENDING_APPROVAL: "CHỜ PHÊ DUYỆT", APPROVED: "ĐÃ PHÊ DUYỆT", REJECTED: "ĐÃ TỪ CHỐI", CREATED: "ĐÃ TẠO", EXECUTING: "ĐANG THỰC HIỆN", VERIFIED: "ĐÃ XÁC MINH", ACTIVE: "ĐANG HOẠT ĐỘNG", DEGRADED: "SUY GIẢM" };
  return labels[status] || String(status || "-").replaceAll("_", " ");
}

function actionTypeVi(type) {
  const labels = { IRRIGATION_PLAN: "Kế hoạch tưới", FIELD_TASK: "Nhiệm vụ hiện trường", ALERT: "Cảnh báo", NOTIFICATION: "Thông báo" };
  return labels[type] || String(type || "Không tạo hành động").replaceAll("_", " ");
}

function agentNameVi(name) {
  const labels = { "Field IoT Agent": "Tác tử IoT hiện trường", "Irrigation Planning Agent": "Tác tử lập kế hoạch tưới", "Resource Agent": "Tác tử tài nguyên", "Farm Action Agent": "Tác tử hành động nông trại", "Farm Coordinator Agent": "Tác tử điều phối nông trại", "Rule Agent": "Tác tử luật" };
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
  const records = knownDevices.map(id => ({ id, item: latestTelemetry[id] }));
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
  message.style.display = ""; // Reset display by default
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
    message.style.display = "none";
  } else {
    message.style.display = "none";
  }
}

function updateSensorFigures(data) {
  if (!document.querySelector("#sensor-figures")) return;

  // 1. SOIL_01
  const soil = data["SOIL_01"]?.metrics || {};
  const soilVal = soil.soil_moisture ?? "—";
  const soilTemp = soil.temperature ?? "—";
  const soilEl = document.querySelector("#fig-soil-val");
  const soilSub = document.querySelector("#fig-soil-sub");
  const soilBar = document.querySelector("#fig-soil-bar");
  const soilStatus = document.querySelector("#fig-soil-status");
  const soilTag = document.querySelector("#fig-soil-tag");

  if (soilEl) soilEl.textContent = `${soilVal}%`;
  if (soilSub) soilSub.textContent = `Nhiệt độ đất: ${soilTemp}°C`;
  if (soilBar) soilBar.style.width = `${Math.max(0, Math.min(100, Number(soilVal) || 0))}%`;
  if (soilStatus && soilTag) {
    if (soilVal !== "—" && Number(soilVal) < 35) {
      soilStatus.className = "figure-badge badge-warn";
      soilStatus.textContent = "⚠️ ĐẤT KHÔ (CẦN TƯỚI)";
      soilTag.textContent = "Độ ẩm < 35% · Khuyên dùng Kế hoạch tưới";
    } else if (soilVal !== "—") {
      soilStatus.className = "figure-badge badge-ok";
      soilStatus.textContent = "✅ ĐỦ ẨM AN TOÀN";
      soilTag.textContent = "Độ ẩm >= 35% · Đất đủ độ ẩm";
    }
  }

  // 2. WEATHER_01
  const weather = data["WEATHER_01"]?.metrics || {};
  const wTemp = weather.temperature ?? "—";
  const wHum = weather.humidity ?? "—";
  const wEl = document.querySelector("#fig-weather-val");
  const wSub = document.querySelector("#fig-weather-sub");
  const wBar = document.querySelector("#fig-weather-bar");
  const wStatus = document.querySelector("#fig-weather-status");
  const wTag = document.querySelector("#fig-weather-tag");

  if (wEl) wEl.textContent = `${wTemp}°C`;
  if (wSub) wSub.textContent = `Độ ẩm KK: ${wHum}%`;
  if (wBar) wBar.style.width = `${Math.max(0, Math.min(100, (Number(wTemp) / 50) * 100 || 0))}%`;
  if (wStatus && wTag) {
    wStatus.className = "figure-badge badge-ok";
    wStatus.textContent = "☀️ THỜI TIẾT";
    wTag.textContent = `Nhiệt độ ${wTemp}°C · Độ ẩm không khí ${wHum}%`;
  }

  // 3. PUMP_01
  const pump = data["PUMP_01"]?.metrics || {};
  const pFlow = pump.flow_rate ?? "—";
  const pPower = pump.power ?? "—";
  const pEl = document.querySelector("#fig-pump-val");
  const pSub = document.querySelector("#fig-pump-sub");
  const pBar = document.querySelector("#fig-pump-bar");
  const pStatus = document.querySelector("#fig-pump-status");
  const pTag = document.querySelector("#fig-pump-tag");

  if (pEl) pEl.textContent = `${pFlow} L/min`;
  if (pSub) pSub.textContent = `Công suất: ${pPower} W`;
  if (pBar) pBar.style.width = `${Math.max(0, Math.min(100, (Number(pFlow) / 30) * 100 || 0))}%`;
  if (pStatus && pTag) {
    if (Number(pFlow) > 0) {
      pStatus.className = "figure-badge badge-ok";
      pStatus.textContent = "💧 BƠM ĐANG CHẠY";
      pTag.textContent = `Lưu lượng dòng chảy: ${pFlow} L/min`;
    } else {
      pStatus.className = "figure-badge badge-info";
      pStatus.textContent = "⏸️ BƠM SẴN SÀNG";
      pTag.textContent = "Máy bơm ở trạng thái chờ lệnh";
    }
  }

  // 4. PH_01
  const phData = data["PH_01"]?.metrics || {};
  const phVal = phData.ph ?? "—";
  const phEl = document.querySelector("#fig-ph-val");
  const phPointer = document.querySelector("#fig-ph-pointer");
  const phStatus = document.querySelector("#fig-ph-status");
  const phTag = document.querySelector("#fig-ph-tag");

  if (phEl) phEl.textContent = `${phVal} pH`;
  if (phPointer) phPointer.style.left = `${Math.max(0, Math.min(100, (Number(phVal) / 14) * 100 || 50))}%`;
  if (phStatus && phTag) {
    if (phVal !== "—" && Number(phVal) >= 5.5 && Number(phVal) <= 7.5) {
      phStatus.className = "figure-badge badge-ok";
      phStatus.textContent = "✅ pH LÝ TƯỞNG";
      phTag.textContent = `Mức pH đất ${phVal} thuộc khoảng an toàn (5.5 - 7.5)`;
    } else if (phVal !== "—") {
      phStatus.className = "figure-badge badge-warn";
      phStatus.textContent = "⚠️ pH LỆCH CHUẨN";
      phTag.textContent = `Mức pH đất ${phVal} nằm ngoài dải an toàn`;
    }
  }

  // 5. TANK_01
  const tank = data["TANK_01"]?.metrics || {};
  const tVal = tank.level ?? tank.tank_level ?? "—";
  const tEl = document.querySelector("#fig-tank-val");
  const tBar = document.querySelector("#fig-tank-bar");
  const tStatus = document.querySelector("#fig-tank-status");
  const tTag = document.querySelector("#fig-tank-tag");

  if (tEl) tEl.textContent = `${tVal}%`;
  if (tBar) tBar.style.width = `${Math.max(0, Math.min(100, Number(tVal) || 0))}%`;
  if (tStatus && tTag) {
    if (tVal !== "—" && Number(tVal) >= 30) {
      tStatus.className = "figure-badge badge-ok";
      tStatus.textContent = "✅ NƯỚC ĐỦ DÙNG";
      tTag.textContent = `Mực nước bồn chứa đạt ${tVal}% (>= 30%)`;
    } else if (tVal !== "—") {
      tStatus.className = "figure-badge badge-warn";
      tStatus.textContent = "⚠️ BỒN CẠN NƯỚC";
      tTag.textContent = `Mực nước bồn chứa thấp (${tVal}% < 30%)`;
    }
  }

  // 6. SUN_01
  const sun = data["SUN_01"]?.metrics || {};
  const sVal = sun.lux ?? "—";
  const sEl = document.querySelector("#fig-sun-val");
  const sBar = document.querySelector("#fig-sun-bar");
  const sStatus = document.querySelector("#fig-sun-status");
  const sTag = document.querySelector("#fig-sun-tag");

  if (sEl) sEl.textContent = `${sVal} lux`;
  if (sBar) sBar.style.width = `${Math.max(0, Math.min(100, (Number(sVal) / 100000) * 100 || 0))}%`;
  if (sStatus && sTag) {
    sStatus.className = "figure-badge badge-ok";
    sStatus.textContent = "☀️ BỨC XẠ XÁC THỰC";
    sTag.textContent = `Bức xạ ánh sáng mặt trời đạt ${sVal} lux`;
  }
}

async function loadTelemetry() {
  const data = await api("/api/telemetry/latest");
  latestTelemetry = data;
  updateSensorFigures(data);
  const devicesEl = document.querySelector("#devices");
  if (devicesEl) {
    devicesEl.innerHTML = knownDevices.map(device => {
      const item = data[device];
      const friendlyName = deviceFriendlyNames[device] || device;
      if (!item) return `<article class="device missing"><div class="device-title"><span class="device-icon">—</span><div><b>${friendlyName}</b><br><small>Chưa nhận dữ liệu cảm biến</small></div></div><div class="meter"><i style="width:8%"></i></div><div class="metrics"><span class="bad">THIẾU DỮ LIỆU</span></div><div class="evidence">Đang chờ dữ liệu</div></article>`;
      const age = Math.max(0, Math.round(Date.now() / 1000 - item.timestamp));
      const freshness = age <= SENSOR_TIMEOUT_SECONDS ? "FRESH" : "OFFLINE";
      const source = item.source_type || "API";
      const strength = Math.max(8, Math.min(100, Number(item.metrics.soil_moisture ?? item.metrics.level ?? item.metrics.humidity ?? item.metrics.flow_rate ?? 55)));
      return `<article class="device ${freshness === "FRESH" ? "fresh" : "missing"}"><div class="device-title"><span class="device-icon">●</span><div><b>${friendlyName}</b><br><small>${source}${source === "MQTT" ? " · TRỰC TIẾP" : ""}</small></div></div><div class="meter"><i style="width:${strength}%"></i></div><div class="metrics">${metricLines(item.metrics)}</div><div class="evidence"><span class="${freshness === "FRESH" ? "ok" : "bad"}">${freshness === "FRESH" ? "DỮ LIỆU MỚI" : "MẤT KẾT NỐI"}</span><br>${age} giây trước<br>${formatTime(item.timestamp)}</div></article>`;
    }).join("");
  }
}

async function drawSensorChart() {
  const specs = [
    { device: "SOIL_01", metric: "soil_moisture", name: "Độ ẩm đất", unit: "%", axis: "Độ ẩm (%)", color: "#10b981", domain: [0, 100], decimals: 1 },
    { device: "WEATHER_01", metric: "temperature", name: "Nhiệt độ không khí", unit: "°C", axis: "Nhiệt độ (°C)", color: "#3b82f6", decimals: 1 },
    { device: "PUMP_01", metric: "flow_rate", name: "Lưu lượng bơm", unit: " L/min", axis: "Lưu lượng (L/min)", color: "#f59e0b", zeroBased: true, decimals: 1 },
    { device: "PH_01", metric: "ph", name: "Độ pH của đất", unit: "", axis: "Độ pH", color: "#a855f7", domain: [0, 14], decimals: 1 },
    { device: "TANK_01", metric: "level", name: "Mực nước bồn", unit: "%", axis: "Mực nước (%)", color: "#ef4444", domain: [0, 100], decimals: 1 },
    { device: "SUN_01", metric: "lux", name: "Cường độ ánh sáng", unit: " lux", axis: "Cường độ sáng (lux)", color: "#eab308", zeroBased: true, decimals: 0 },
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
    .map(row => ({ timestamp: Number(row.timestamp), value: Number(row.metrics?.[spec.metric]) }))
    .filter(sample => Number.isFinite(sample.timestamp) && Number.isFinite(sample.value) && sample.timestamp >= windowStart)
    .sort((a, b) => a.timestamp - b.timestamp);
  const liveValue = Number(latestTelemetry[spec.device]?.metrics?.[spec.metric]);
  const currentValue = Number.isFinite(liveValue) ? liveValue : samples.at(-1)?.value;
  const currentLabel = Number.isFinite(currentValue) ? `${formatChartValue(currentValue, spec)}${spec.unit}` : "—";
  const header = `<div class="mini-chart-head"><span class="mini-chart-id">${spec.device}</span><strong class="mini-chart-value">${currentLabel}</strong><span class="mini-chart-name">${spec.name}</span></div>`;
  if (!samples.length) return `<article class="mini-chart">${header}<div class="chart-empty">Đang chờ dữ liệu lịch sử từ MQTT...</div></article>`;

  const values = samples.map(sample => sample.value);
  const [domainMin, domainMax] = chartDomain(spec, values);
  const width = 380, height = 190, left = 54, right = 368, top = 17, bottom = 145;
  const x = timestamp => left + ((Math.min(now, Math.max(windowStart, timestamp)) - windowStart) / (now - windowStart)) * (right - left);
  const y = value => bottom - ((value - domainMin) / (domainMax - domainMin)) * (bottom - top);
  const points = samples.map(sample => `${x(sample.timestamp).toFixed(1)},${y(sample.value).toFixed(1)}`).join(" ");
  const yTicks = [domainMax, (domainMin + domainMax) / 2, domainMin];
  const grid = yTicks.map((tick, tickIndex) => { const py = top + tickIndex * ((bottom - top) / 2); return `<line class="mini-chart-grid" x1="${left}" y1="${py}" x2="${right}" y2="${py}"/><text class="mini-chart-axis" x="${left - 7}" y="${py + 3}" text-anchor="end">${formatAxisValue(tick, spec)}</text>`; }).join("");
  const timeTicks = [windowStart, windowStart + 15 * 60, now];
  const timeLabels = timeTicks.map((timestamp, tickIndex) => `<text class="mini-chart-axis" x="${x(timestamp)}" y="169" text-anchor="${tickIndex === 0 ? "start" : tickIndex === 2 ? "end" : "middle"}">${tickIndex === 2 ? "Hiện tại" : formatChartTime(timestamp)}</text>`).join("");
  const circles = samples.map(sample => `<circle class="chart-point" tabindex="0" cx="${x(sample.timestamp).toFixed(1)}" cy="${y(sample.value).toFixed(1)}" r="2.6" fill="${spec.color}" data-chart-point data-time="${sample.timestamp}" data-value="${sample.value}" data-name="${spec.name}" data-unit="${escapeHtml(spec.unit)}" data-decimals="${spec.decimals}" aria-label="${spec.name}, ${formatChartValue(sample.value, spec)}${spec.unit}, ${formatChartTime(sample.timestamp)}"/>`).join("");
  return `<article class="mini-chart">${header}<svg class="mini-chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Các chỉ số của ${spec.name} trong 30 phút qua"><text class="mini-chart-axis" transform="translate(10 82) rotate(-90)" text-anchor="middle">${spec.axis}</text>${grid}<polyline class="mini-chart-line" points="${points}" stroke="${spec.color}"/>${circles}${timeLabels}</svg><div class="chart-tooltip" role="tooltip"></div></article>`;
}

function chartDomain(spec, values) {
  if (spec.domain) return spec.domain;
  const min = Math.min(...values), max = Math.max(...values);
  if (spec.zeroBased) return [0, Math.max(1, max * 1.15)];
  const padding = Math.max((max - min) * .18, 1);
  return [min - padding, max + padding];
}

function formatChartValue(value, spec) {
  return Number(value).toLocaleString("vi-VN", { minimumFractionDigits: spec.decimals, maximumFractionDigits: spec.decimals });
}

function formatAxisValue(value, spec) {
  const decimals = spec.metric === "ph" ? 1 : Math.abs(value) >= 1000 ? 0 : Math.abs(value) < 10 ? 1 : 0;
  return Number(value).toLocaleString("vi-VN", { maximumFractionDigits: decimals });
}

function formatChartTime(epoch) {
  return new Date(epoch * 1000).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
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
      const value = Number(point.dataset.value).toLocaleString("vi-VN", { minimumFractionDigits: Number(point.dataset.decimals), maximumFractionDigits: Number(point.dataset.decimals) });
      tooltip.innerHTML = `<span class="chart-tooltip-time">${new Date(Number(point.dataset.time) * 1000).toLocaleTimeString("vi-VN", { hour: "numeric", minute: "2-digit" })}</span><b>${point.dataset.name}: ${value}${point.dataset.unit}</b>`;
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
  if (!item) return { freshness: "offline", violated: false };
  const age = Math.max(0, Date.now() / 1000 - item.timestamp);
  const freshness = age > SENSOR_TIMEOUT_SECONDS ? "offline" : "fresh";
  const m = item.metrics || {};
  const violated = freshness === "fresh" && (deviceId === "SOIL_01" ? Number(m.soil_moisture) < 30 : deviceId === "TANK_01" ? Number(m.tank_level ?? m.level) < 20 : deviceId === "PUMP_01" ? String(m.pump_status).toUpperCase() === "ERROR" || Number(m.pump_status) === 0 : deviceId === "PH_01" ? Number(m.ph) < 5.5 || Number(m.ph) > 7.5 : false);
  return { freshness, violated };
}

function worstZoneStatus(ids) {
  const states = ids.map(sensorState);
  if (states.some(s => s.freshness === "offline")) return "offline";
  return "normal";
}

function renderFarmMap(selectedId = null) {
  const svg = document.querySelector("#farm-map"); if (!svg) return;
  const styles = {
    critical: { fill: "#fef2f2", stroke: "#ef4444", label: "NGUY CẤP" },
    stale: { fill: "#fff7ed", stroke: "#ea580c", label: "DỮ LIỆU CŨ" },
    offline: { fill: "#fafaf9", stroke: "#64748b", label: "MẤT KẾT NỐI" },
    normal: { fill: "#f0fdf4", stroke: "#16a34a", label: "BÌNH THƯỜNG" }
  };
  const ids = ["SOIL_01", "WEATHER_01", "PUMP_01", "PH_01", "TANK_01", "SUN_01"];
  const labels = { SOIL_01: "SOIL_01", WEATHER_01: "WEATHER_01", PUMP_01: "PUMP_01", PH_01: "PH_01", TANK_01: "TANK_01", SUN_01: "SUN_01" };
  const roles = { SOIL_01: "Đất", WEATHER_01: "Thời tiết", PUMP_01: "Máy bơm", PH_01: "Độ pH", TANK_01: "Bồn chứa", SUN_01: "Ánh sáng" };
  const positions = { SOIL_01: [155, 155], WEATHER_01: [430, 155], PUMP_01: [705, 155], PH_01: [155, 290], TANK_01: [430, 290], SUN_01: [705, 290] };
  const style = styles[worstZoneStatus(ids)];
  const zoneSvg = `<g><rect x="20" y="24" width="820" height="372" rx="22" fill="${style.fill}" stroke="${style.stroke}" stroke-width="2"/><text x="46" y="58" fill="${style.stroke}" font-size="17" font-weight="700">Vùng nông trại 1</text><text x="46" y="79" fill="#64748b" font-size="11">6 vị trí cảm biến được giám sát</text><rect x="720" y="42" width="92" height="27" rx="14" fill="${style.stroke}"/><text x="766" y="60" text-anchor="middle" fill="#fff" font-size="11" font-weight="800">${style.label}</text><path d="M52 100 H808 M292 108 V365 M568 108 V365 M52 230 H808" stroke="#cbd5e1" stroke-width="1" stroke-dasharray="5 7" opacity=".55"/></g>`;
  const pinSvg = Object.entries(positions).map(([id, [x, y]]) => {
    const state = sensorState(id);
    const color = state.freshness === "offline" ? "#ef4444" : "#16a34a";
    return `<g class="sensor-node" data-sensor="${id}" style="cursor:pointer"><rect class="sensor-card" x="${x - 108}" y="${y - 43}" width="216" height="86" rx="15" fill="#ffffff" stroke="${state.freshness === "offline" ? "#ef4444" : "#e2e8f0"}" stroke-width="1.5"/><circle cx="${x - 75}" cy="${y}" r="16" fill="${color}" stroke="#ffffff" stroke-width="2"/><text x="${x - 48}" y="${y - 5}" fill="#0f172a" font-size="14" font-weight="700">${labels[id]}</text><text x="${x - 48}" y="${y + 15}" fill="${state.freshness === "offline" ? "#ef4444" : "#64748b"}" font-size="11">${roles[id]} · ${state.freshness === 'fresh' ? 'MỚI' : 'MẤT KẾT NỐI'}</text></g>`
  }).join("");
  let popup = "";
  if (selectedId && positions[selectedId]) {
    const [x, y] = positions[selectedId];
    const item = latestTelemetry[selectedId];
    const state = sensorState(selectedId);
    const px = Math.max(30, Math.min(580, x > 560 ? x - 270 : x + 30)), py = Math.max(88, Math.min(205, y > 230 ? y - 180 : y - 58));
    const age = item ? Math.max(0, Math.round(Date.now() / 1000 - item.timestamp)) : null;
    const ageLabel = age === null ? "Chưa nhận dữ liệu" : age <= 1 ? "Vừa cập nhật tức thì" : `Cập nhật ${age} giây trước`;
    popup = `<foreignObject class="sensor-popup" x="${px}" y="${py}" width="250" height="190"><div xmlns="http://www.w3.org/1999/xhtml" style="background:#ffffff;border:1px solid #cbd5e1;border-radius:13px;padding:12px;color:#0f172a;font:12px Segoe UI,Arial;box-shadow:0 12px 28px rgba(15,23,42,0.15)"><div style="display:flex;justify-content:space-between;align-items:center"><b style="font-size:14px">${labels[selectedId]}</b><span style="color:${state.freshness === 'fresh' ? '#16a34a' : '#ef4444'};font-weight:700">${state.freshness === 'fresh' ? 'MỚI' : 'MẤT KẾT NỐI'}</span></div><hr style="border:0;border-top:1px solid #e2e8f0;margin:8px 0"/><div class="metrics">${item ? metricLines(item.metrics) : '<span>Ngoại tuyến — không có dữ liệu</span>'}</div><div style="color:#64748b;margin-top:8px">${ageLabel}</div><button data-history="${selectedId}" style="margin-top:8px;padding:5px 9px">Xem lịch sử</button></div></foreignObject>`;
  }
  if (!Object.keys(latestTelemetry).length) popup += `<text x="430" y="205" text-anchor="middle" fill="#64748b" font-size="18">Không có dữ liệu cảm biến</text>`;
  svg.innerHTML = zoneSvg + pinSvg + popup;
  svg.querySelectorAll("[data-sensor]").forEach(pin => pin.addEventListener("click", event => { event.stopPropagation(); renderFarmMap(pin.dataset.sensor) }));
  svg.querySelector("[data-history]")?.addEventListener("click", event => { event.stopPropagation(); showMapHistory(event.target.dataset.history) });
  svg.onclick = event => { if (!event.target.closest(".sensor-node") && !event.target.closest(".sensor-popup")) renderFarmMap(); };
}

async function showMapHistory(deviceId) {
  const history = await api(`/api/telemetry/history?device_id=${deviceId}&limit=5`);
  const target = document.querySelector("#map-history");
  const displayId = deviceId === "PUMP_01" ? "PUMP_01 (Máy bơm nước)" : deviceFriendlyNames[deviceId] || deviceId;
  target.innerHTML = `<div class="eyebrow">Lịch sử cảm biến</div><h2>${displayId}</h2><p class="muted">5 bản ghi gần nhất</p>${history.length ? history.map(row => `<div class="history-row"><span>${formatTime(row.timestamp)}</span><span class="tag">${row.source_type}</span><span>${Object.entries(row.metrics).map(([k, v]) => `${escapeHtml(k.replaceAll("_", " "))}: ${escapeHtml(v)}`).join(" · ")}</span></div>`).join("") : "<p>Không có dữ liệu lịch sử.</p>"}`;
}

async function loadSnapshot() {
  const snapshot = await api("/api/telemetry/snapshot");
  const target = document.querySelector("#snapshot-summary");
  if (!target) return;
  if (snapshot.ready_for_ai) {
    target.innerHTML = `<span class="ok">SẴN SÀNG: Đã có dữ liệu MQTT trực tiếp.</span> Chủ đề (Topic): <code>${escapeHtml(snapshot.topic)}</code>`;
  } else {
    target.innerHTML = `<span class="warn">AI TRỰC TIẾP CHƯA SẴN SÀNG:</span> ${snapshot.issues.map(escapeHtml).join(" · ")}`;
  }
}

function renderAgentSelector() {
  document.querySelector("#agent-selector").innerHTML = agentConfigs.map(agent => `
    <label class="agent">
      <span class="agent-title">
        <input type="checkbox" value="${agent.agent_id}" ${agent.enabled && agent.connection_status === "READY" ? "checked" : ""}>
        <span class="agent-name">${escapeHtml(agent.display_name)}</span>
      </span>
      <span class="agent-role">${escapeHtml(agent.role)}</span>
      <span class="agent-meta">
        <span class="${agent.connection_status === "READY" ? "ok" : "warn"}">${agent.connection_status === 'READY' ? 'SẴN SÀNG' : statusVi(agent.connection_status)}</span> · ${escapeHtml(agent.provider)}/${escapeHtml(agent.model)}
      </span>
    </label>
  `).join("");
  const updateSummary = () => {
    const selected = [...document.querySelectorAll("#agent-selector input:checked")].map(input => agentConfigs.find(agent => agent.agent_id === input.value)?.display_name).filter(Boolean);
    const target = document.querySelector("#ai-selection-summary");
    if (target) target.textContent = selected.length ? `AI đã chọn: ${selected.join(" · ")}` : "Chưa chọn nhà cung cấp AI. Hãy mở Cài đặt AI để chọn.";
  };
  document.querySelectorAll("#agent-selector input").forEach(input => input.addEventListener("change", updateSummary));
  updateSummary();
}

function renderAgentConfigs() {
  document.querySelector("#agent-configs").innerHTML = agentConfigs.map(agent => `<article class="agent" data-agent="${agent.agent_id}"><div class="section-head"><div class="agent-header-info"><b class="agent-name">${escapeHtml(agent.display_name)}</b><p class="muted">${escapeHtml(agent.role)}</p></div><span class="tag ${agent.connection_status === "READY" ? "ok" : "warn"}">${agent.connection_status}</span></div><div class="two"><label>Provider<select class="provider"><option value="openai" ${agent.provider === "openai" ? "selected" : ""}>ChatGPT / OpenAI</option><option value="gemini" ${agent.provider === "gemini" ? "selected" : ""}>Google Gemini</option><option value="anthropic" ${agent.provider === "anthropic" ? "selected" : ""}>Claude / Anthropic</option><option value="deepseek" ${agent.provider === "deepseek" ? "selected" : ""}>DeepSeek</option></select></label><label>Model<input class="model" value="${escapeHtml(agent.model)}" maxlength="120"></label></div><label>API key<input class="api-key" type="password" autocomplete="new-password" placeholder="Enter a new or replacement API key"></label><label><input class="enabled" type="checkbox" ${agent.enabled ? "checked" : ""}> Enable this provider</label><div class="row"><button class="save-agent secondary">Save settings</button><button class="test-agent">Test connection</button></div><span class="agent-message evidence">${agent.has_api_key ? (agent.has_custom_key ? "Đã nhập API key tùy chỉnh (ưu tiên dùng)" : "Tự động dùng API key mặc định trong .env") : "Chưa có API key"}${agent.last_error ? ` · ${escapeHtml(agent.last_error)}` : ""}</span></article>`).join("");
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
  event.target.disabled = true;
  try {
    await api(`/api/agents/${card.dataset.agent}/config`, { method: "PUT", body: JSON.stringify({ provider: card.querySelector(".provider").value, model: card.querySelector(".model").value.trim(), api_key: key, enabled: card.querySelector(".enabled").checked }) });
    message.textContent = key ? "Đã lưu API key tùy chỉnh." : "Đã lưu (đang tự động dùng API key mặc định trong .env).";
    card.querySelector(".api-key").value = "";
    await loadAgents();
  } catch (error) { message.textContent = `Unable to save: ${JSON.stringify(error)}`; }
  finally { event.target.disabled = false; }
}

async function testAgent(event) {
  const card = event.target.closest("[data-agent]");
  const message = card.querySelector(".agent-message");
  event.target.disabled = true; message.textContent = "Connecting to the live provider...";
  try { await api(`/api/agents/${card.dataset.agent}/test-connection`, { method: "POST" }); message.textContent = "READY — live provider connection succeeded."; }
  catch (error) { message.textContent = `FAILED: ${JSON.stringify(error)}`; }
  finally { event.target.disabled = false; await loadAgents(); }
}

function renderRun(result) {
  const target = document.querySelector("#run-result");
  if (!target) return;
  target.className = "";

  const narrative = result.narrative_summary || result.summary || "Hệ thống đã hoàn thành phân tích đàm phán.";
  const dialogues = result.agent_dialogue || [];
  const dialogueHtml = dialogues.map(item => `
    <div class="trace">
      <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px;">
        <b style="font-size: 14px;">${escapeHtml(item.speaker || item.agent)}</b>
        <span class="tag">${escapeHtml(item.llm_model || item.llm_slot || "LLM")}</span>
      </div>
      <p style="margin: 6px 0 0; font-size: 14px; line-height: 1.5;">${escapeHtml(item.message)}</p>
    </div>
  `).join("");

  target.innerHTML = `
    <div class="dialogue-narrative-card">
      <h3>Báo cáo diễn giải cuộc trò chuyện AI</h3>
      <p>${escapeHtml(narrative)}</p>
    </div>
    <div style="display: flex; gap: 10px; margin-bottom: 12px; flex-wrap: wrap;">
      <span class="tag tag-success">Mã Lệnh: ${escapeHtml(result.action_type || "IRRIGATION_PLAN")}</span>
      <span class="tag">Trạng thái: ${escapeHtml(result.verification_status || "VERIFIED")}</span>
    </div>
    <div class="eyebrow" style="margin-bottom: 8px;">Nhật ký trao đổi đàm phán giữa các Agents</div>
    ${dialogueHtml || '<p class="subtitle-text">Chưa có nhật ký trao đổi.</p>'}
  `;
}

async function runCoordination() {
  const button = document.querySelector("#run");
  if (button) button.disabled = true;
  setRunStatus("Đang đọc dữ liệu cảm biến và khởi chạy đàm phán 4 LLM Agents...", "warn");
  try {
    const scenarioText = (document.querySelector("#scenario")?.value || "").trim() || "Hãy kiểm tra và lập kế hoạch tưới hôm nay";
    const result = await api("/api/dialogue/summary", {
      method: "POST",
      body: JSON.stringify({ request: scenarioText, manager_name: "Quản lý Trang trại A" })
    });
    renderRun(result);
    setRunStatus("Hoàn thành đàm phán 4 AI Agents. Lệnh đã tạo chờ duyệt.", "ok");
    if (typeof loadActions === "function") await loadActions();
  } catch (error) {
    setRunStatus(`Lỗi kết nối API: ${JSON.stringify(error)}`, "bad");
  } finally {
    if (button) button.disabled = false;
  }
}

async function loadActions() {
  const actions = await api("/api/actions");
  latestActions = actions;
  renderExecutiveSummary();
  const container = document.querySelector("#actions-list");
  if (!container) return;

  const displayableActions = actions.filter(action => !(action.action_type === "FIELD_TASK" && action.status === "CREATED"));

  if (displayableActions.length === 0) {
    container.innerHTML = `<div class="result-empty" style="grid-column: 1 / -1;">Hiện chưa có tác vụ nào cần phê duyệt. Các đề xuất do AI khởi tạo sẽ xuất hiện tại đây.</div>`;
    return;
  }

  const actionCards = displayableActions.map(action => {
    const isPending = action.status === "PENDING_APPROVAL";
    const isApproved = ["APPROVED", "EXECUTING"].includes(action.status);
    const isVerified = action.status === "VERIFIED";
    const isRejected = action.status === "REJECTED";

    let statusTagClass = "tag";
    let statusText = statusVi(action.status);
    if (isPending) { statusTagClass = "tag tag-warning"; statusText = "CHỜ PHÊ DUYỆT"; }
    else if (isApproved || isVerified) { statusTagClass = "tag tag-success"; statusText = isVerified ? "ĐÃ XÁC MINH" : "ĐÃ PHÊ DUYỆT"; }
    else if (isRejected) { statusTagClass = "tag tag-danger"; statusText = "ĐÃ TỪ CHỐI"; }

    const typeLabel = actionTypeVi(action.action_type);
    const reasonText = action.payload?.reason || action.payload?.schedule?.target_zone || "Xem chi tiết bằng chứng trong hồ sơ công việc.";

    return `
      <article class="action-card">
        <div class="action-card-head">
          <b>${escapeHtml(typeLabel)}</b>
          <span class="${statusTagClass}">${escapeHtml(statusText)}</span>
        </div>
        <p class="action-card-meta">Mã: ${escapeHtml(action.id)} · ${formatTime(action.created_at)}</p>
        <p class="action-card-body">${escapeHtml(reasonText)}</p>
        <div class="action-card-actions">
          ${isPending ? `
            <button class="btn-primary btn-sm" data-approval="APPROVE" data-id="${action.id}">Đồng ý duyệt</button>
            <button class="danger btn-sm" data-approval="REJECT" data-id="${action.id}">Từ chối</button>
          ` : ""}
          ${isApproved ? `
            <button class="btn-secondary btn-sm" data-verify="${action.id}">Xác minh dữ liệu</button>
          ` : ""}
        </div>
      </article>
    `;
  });

  container.innerHTML = actionCards.join("");
  document.querySelectorAll("[data-approval]").forEach(button => button.addEventListener("click", approveAction));
  document.querySelectorAll("[data-verify]").forEach(button => button.addEventListener("click", verifyAction));
}

async function approveAction(event) {
  const note = window.prompt("Nhập ghi chú điều chỉnh công việc hoặc nguyên nhân từ chối (không bắt buộc):", "") ?? "";
  try { await api(`/api/actions/${event.target.dataset.id}/approval`, { method: "PATCH", body: JSON.stringify({ decision: event.target.dataset.approval, operator_note: note }) }); await loadActions(); }
  catch (error) { window.alert(`Không thể cập nhật quyết định: ${JSON.stringify(error)}`); }
}

async function verifyAction(event) {
  try { const result = await api(`/api/actions/${event.target.dataset.verify}/verify`, { method: "POST" }); window.alert(result.verification_status === "VERIFIED" ? "Verified with MQTT pump telemetry." : "No new MQTT actuator telemetry is available. The action remains unverified."); await loadActions(); }
  catch (error) { window.alert(`Unable to verify the action: ${JSON.stringify(error)}`); }
}

async function clearActionsHistory() {
  if (!window.confirm("Bạn có chắc chắn muốn xóa toàn bộ lịch sử công việc không?")) return;
  try {
    await api("/api/actions", { method: "DELETE" });
    await loadActions();
  } catch (error) {
    window.alert(`Không thể xóa danh sách tác vụ: ${JSON.stringify(error)}`);
  }
}

function activateTab(name) {
  document.querySelectorAll(".tab").forEach(item => item.classList.toggle("active", item.dataset.tab === name));
  document.querySelectorAll("main > .panel").forEach(panel => panel.classList.toggle("active", panel.id === name));
  if (name === "dashboard" && typeof renderFarmMap === "function") renderFarmMap();
}

const runBtn = document.querySelector("#run");
if (runBtn) runBtn.addEventListener("click", runCoordination);

const refreshBtn = document.querySelector("#refresh");
if (refreshBtn) refreshBtn.addEventListener("click", () => { if (typeof refreshAll === "function") refreshAll(); });

const refreshActionsBtn = document.querySelector("#refresh-actions");
if (refreshActionsBtn) refreshActionsBtn.addEventListener("click", loadActions);

const clearActionsBtn = document.querySelector("#clear-actions");
if (clearActionsBtn) clearActionsBtn.addEventListener("click", clearActionsHistory);

document.querySelectorAll(".prompt-btn").forEach(button => button.addEventListener("click", () => {
  const scenario = document.querySelector("#scenario");
  if (scenario) scenario.value = button.dataset.prompt;
}));

async function fetchLatestDialogueSummary() {
  try {
    const summaryData = await api("/api/dialogue/summary", { method: "GET" });
    if (summaryData && summaryData.narrative_summary) {
      const executiveMsg = document.querySelector("#executive-message");
      if (executiveMsg) {
        executiveMsg.className = "executive-message";
        executiveMsg.innerHTML = `<b>Tóm tắt chỉ đạo đàm phán AI gần nhất:</b> ${escapeHtml(summaryData.narrative_summary)}`;
      }
      const runResult = document.querySelector("#run-result");
      if (runResult && (runResult.classList.contains("result-empty") || runResult.innerHTML.includes("Hệ thống đang chờ"))) {
        renderRun(summaryData);
      }
    }
  } catch (err) {
    console.warn("Lỗi gọi GET /api/dialogue/summary:", err);
  }
}

const fetchDialogueSummaryBtn = document.querySelector("#fetch-dialogue-summary-btn");
if (fetchDialogueSummaryBtn) {
  fetchDialogueSummaryBtn.addEventListener("click", async () => {
    setRunStatus("Đang nạp tóm tắt đàm phán...", "warn");
    await fetchLatestDialogueSummary();
    setRunStatus("Đã cập nhật tóm tắt đàm phán.", "ok");
  });
}

document.querySelectorAll(".demo").forEach(button => button.addEventListener("click", async () => { await api("/api/demo/seed", { method: "POST", body: JSON.stringify({ scenario: button.dataset.scenario }) }); await loadTelemetry(); window.alert(`Demo scenario loaded: ${button.textContent}. Demo data cannot trigger a live MQTT AI decision.`); }));

function connectRealtime() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${location.host}/ws/telemetry`);
  socket.onmessage = () => { loadTelemetry().catch(() => { }); loadSnapshot().catch(() => { }); loadActions().catch(() => { }); };
  socket.onclose = () => setTimeout(connectRealtime, 2000);
}

Promise.all([loadHealth(), loadTelemetry(), loadAgents(), loadActions(), fetchLatestDialogueSummary()]).catch(error => setRunStatus(`Unable to connect to the API: ${JSON.stringify(error)}`, "bad"));


let countdown = 10;
async function refreshAll() {
  countdown = 10;
  const btn = document.querySelector("#refresh");
  if (btn) btn.textContent = `Làm mới dữ liệu (${countdown}s)`;
  await Promise.all([loadTelemetry(), loadHealth()]).catch(() => { });
}
setInterval(() => {
  countdown--;
  if (countdown <= 0) {
    refreshAll();
  } else {
    const btn = document.querySelector("#refresh");
    if (btn) btn.textContent = `Làm mới dữ liệu (${countdown}s)`;
  }
}, 1000);

connectRealtime();

