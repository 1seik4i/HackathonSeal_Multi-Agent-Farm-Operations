import {
  ResponsiveContainer,
  LineChart,
  Line,
  AreaChart,
  Area,
  BarChart,
  Bar,
  Tooltip,
  ReferenceLine,
} from "recharts";

const CONFIG = {
  SOIL_01: {
    label: "Độ ẩm đất",
    unit: "%",
    primary: (m) => m?.soil_moisture,
    secondary: (m) => (m?.temperature != null ? `Đất ${m.temperature}°C` : ""),
    series: [
      { key: "moisture", color: "#1f6b45" },
      { key: "temp", color: "#b45309" },
    ],
    map: (item) => ({
      moisture: item.metrics?.soil_moisture ?? null,
      temp: item.metrics?.temperature ?? null,
    }),
    threshold: 35,
  },
  WEATHER_01: {
    label: "Nhiệt độ không khí",
    unit: "°C",
    primary: (m) => m?.temperature,
    secondary: (m) => (m?.humidity != null ? `Ẩm ${m.humidity}%` : ""),
    series: [
      { key: "temp", color: "#1f6b45" },
      { key: "humidity", color: "#3b82a0" },
    ],
    map: (item) => ({
      temp: item.metrics?.temperature ?? null,
      humidity: item.metrics?.humidity ?? null,
    }),
  },
  SUN_01: {
    label: "Ánh sáng",
    unit: "lux",
    primary: (m) => m?.lux,
    secondary: () => "",
    series: [{ key: "lux", color: "#a16207" }],
    map: (item) => ({ lux: item.metrics?.lux ?? null }),
    chart: "area",
  },
  PUMP_01: {
    label: "Lưu lượng bơm",
    unit: "L/min",
    primary: (m) => m?.flow_rate,
    secondary: (m) => (m?.power != null ? `${m.power} W` : ""),
    series: [{ key: "flow_rate", color: "#1f6b45" }],
    map: (item) => ({ flow_rate: item.metrics?.flow_rate ?? null }),
    chart: "bar",
  },
  PH_01: {
    label: "pH đất",
    unit: "",
    primary: (m) => m?.ph,
    secondary: () => "An toàn 5.5–7.5",
    series: [{ key: "ph", color: "#0f766e" }],
    map: (item) => ({ ph: item.metrics?.ph ?? null }),
  },
  TANK_01: {
    label: "Mức bồn nước",
    unit: "%",
    primary: (m) => m?.level,
    secondary: () => "Tối thiểu 30%",
    series: [{ key: "level", color: "#0e7490" }],
    map: (item) => ({ level: item.metrics?.level ?? null }),
    chart: "area",
    threshold: 30,
  },
};

function formatPrimary(value, unit) {
  if (value == null || Number.isNaN(value)) return "--";
  if (unit === "lux") return `${Number(value).toLocaleString("vi-VN")} lux`;
  return `${value}${unit ? ` ${unit}` : ""}`.trim();
}

export function SensorBoard({ devices, telemetry, historyMap }) {
  return (
    <section>
      <h2 className="section-title">Cảm biến thời gian thực</h2>
      <p className="section-sub">Sáu nguồn dữ liệu nông trại — một khối, cập nhật liên tục.</p>
      <div className="sensor-grid">
        {devices.map((code) => {
          const cfg = CONFIG[code];
          const metrics = telemetry?.[code]?.metrics;
          const chartData = (historyMap?.[code] || []).map((item, index) => ({
            i: index,
            time: item.timestamp
              ? new Date(item.timestamp * 1000).toLocaleTimeString("vi-VN", {
                  hour: "2-digit",
                  minute: "2-digit",
                })
              : String(index),
            ...cfg.map(item),
          }));
          const fresh =
            telemetry?.[code]?.quality?.freshness === "FRESH" ||
            telemetry?.[code]?.quality == null;

          return (
            <article key={code} className="sensor-cell">
              <div className="meta">
                <span className="code">
                  {code} · {fresh ? "live" : "stale"}
                </span>
                <span className="reading">{formatPrimary(cfg.primary(metrics), cfg.unit)}</span>
              </div>
              <div className="hint">
                {cfg.label}
                {cfg.secondary(metrics) ? ` · ${cfg.secondary(metrics)}` : ""}
              </div>
              <div className="chart-box">
                <ResponsiveContainer width="100%" height="100%">
                  {cfg.chart === "area" ? (
                    <AreaChart data={chartData} margin={{ top: 4, right: 4, left: -28, bottom: 0 }}>
                      <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                      {cfg.threshold != null && (
                        <ReferenceLine y={cfg.threshold} stroke="#b45309" strokeDasharray="3 3" />
                      )}
                      <Area
                        type="monotone"
                        dataKey={cfg.series[0].key}
                        stroke={cfg.series[0].color}
                        fill={cfg.series[0].color}
                        fillOpacity={0.15}
                        strokeWidth={2}
                        dot={false}
                      />
                    </AreaChart>
                  ) : cfg.chart === "bar" ? (
                    <BarChart data={chartData} margin={{ top: 4, right: 4, left: -28, bottom: 0 }}>
                      <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                      <Bar dataKey={cfg.series[0].key} fill={cfg.series[0].color} radius={[3, 3, 0, 0]} />
                    </BarChart>
                  ) : (
                    <LineChart data={chartData} margin={{ top: 4, right: 4, left: -28, bottom: 0 }}>
                      <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                      {cfg.threshold != null && (
                        <ReferenceLine y={cfg.threshold} stroke="#b45309" strokeDasharray="3 3" />
                      )}
                      {cfg.series.map((s) => (
                        <Line
                          key={s.key}
                          type="monotone"
                          dataKey={s.key}
                          stroke={s.color}
                          strokeWidth={2}
                          dot={false}
                        />
                      ))}
                    </LineChart>
                  )}
                </ResponsiveContainer>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
