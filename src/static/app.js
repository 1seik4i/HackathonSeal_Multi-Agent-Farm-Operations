const devices = document.querySelector("#devices");
const result = document.querySelector("#result");
const status = document.querySelector("#status");

async function loadTelemetry() {
  const response = await fetch("/api/telemetry/latest");
  const data = await response.json();
  const known = ["SOIL_01", "WEATHER_01", "PUMP_01", "PH_01", "TANK_01", "SUN_01"];
  devices.innerHTML = known.map((device) => {
    const value = data[device];
    if (!value) return `<article class="device"><b>${device}</b><br><small class="warn">MISSING</small></article>`;
    const age = Math.max(0, Math.round(Date.now() / 1000 - value.timestamp));
    return `<article class="device"><b>${device}</b><br><small>${age}s ago</small><br><small>${JSON.stringify(value.metrics)}</small></article>`;
  }).join("");
}

document.querySelector("#run").addEventListener("click", async () => {
  status.textContent = "Đang phối hợp Agent…";
  const response = await fetch("/api/coordinate", {method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({request:document.querySelector("#request").value})});
  result.textContent = JSON.stringify(await response.json(), null, 2);
  status.textContent = "Hoàn tất; action đã được verification.";
  loadTelemetry();
});
document.querySelector("#seed").addEventListener("click", async () => {
  await fetch("/api/demo/seed", { method: "POST" });
  status.textContent = "Đã nạp dữ liệu mẫu của 6 thiết bị.";
  loadTelemetry();
});
loadTelemetry(); setInterval(loadTelemetry, 5000);
