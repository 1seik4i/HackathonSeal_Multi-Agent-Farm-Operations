import { Link } from "react-router-dom";
import { useFarmData } from "../context/FarmDataContext";
import { SensorBoard } from "../components/SensorBoard";

export function MonitorPage() {
  const {
    DEVICES,
    telemetry,
    historyMap,
    verdict,
    pendingApprovals,
    systemStatus,
    agentHealth,
  } = useFarmData();

  const soil = telemetry.SOIL_01?.metrics?.soil_moisture;
  const weather = telemetry.WEATHER_01?.metrics?.temperature;
  const tank = telemetry.TANK_01?.metrics?.level;
  const pump = telemetry.PUMP_01?.metrics?.flow_rate;

  return (
    <main>
      {agentHealth?.fallback_active && (
        <div
          style={{
            backgroundColor: "#fef2f2",
            border: "1px solid #fecaca",
            borderRadius: "10px",
            padding: "1rem 1.25rem",
            marginBottom: "1.25rem",
            color: "#991b1b",
            boxShadow: "0 2px 8px rgba(220, 38, 38, 0.08)",
          }}
        >
          <div style={{ fontWeight: 700, fontSize: "1.05rem", display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
            <span>⚠️ CẢNH BÁO: PHÁT HIỆN SỰ CỐ AI AGENT</span>
            <span
              style={{
                backgroundColor: "#dc2626",
                color: "#fff",
                padding: "0.2rem 0.6rem",
                borderRadius: "999px",
                fontSize: "0.75rem",
                fontWeight: 800,
                letterSpacing: "0.03em",
              }}
            >
              CHẾ ĐỘ THUẦN LOGIC ĐANG KÍCH HOẠT
            </span>
          </div>
          <p style={{ margin: "0.6rem 0 0.3rem", fontSize: "0.95rem", lineHeight: 1.5 }}>
            Hệ thống đã tự động xác định <strong>{agentHealth.failed_agents.length} AI Agent gặp lỗi / không phản hồi</strong>:
          </p>
          <ul style={{ margin: "0.25rem 0 0.6rem 1.25rem", padding: 0, fontSize: "0.9rem" }}>
            {agentHealth.failed_agents.map((fa, i) => (
              <li key={i} style={{ marginBottom: "0.2rem" }}>
                <strong>{fa.agent}</strong> ({fa.model}): <span style={{ color: "#7f1d1d" }}>{fa.error}</span>
              </li>
            ))}
          </ul>
          <div
            style={{
              fontSize: "0.88rem",
              fontWeight: 600,
              color: "#166534",
              backgroundColor: "#f0fdf4",
              border: "1px solid #bbf7d0",
              padding: "0.5rem 0.85rem",
              borderRadius: "6px",
              lineHeight: 1.5,
            }}
          >
            💡 <strong>Hệ thống Bảo vệ Tự động:</strong> Đã chuyển ngay sang bộ thuật toán thuần logic (kiểm tra độ ẩm đất thấp/cao, nước bồn, pH, trạng thái máy bơm) để tiếp tục duy trì hệ thống không gián đoạn!
          </div>
        </div>
      )}

      <section className="hero-block">
        <div>
          <div className={`verdict ${verdict.tone}`}>{verdict.code}</div>
          <h1
            className="brand-font"
            style={{
              fontSize: "clamp(2rem, 4.5vw, 3.1rem)",
              fontWeight: 800,
              letterSpacing: "-0.04em",
              lineHeight: 1.05,
              margin: "0.45rem 0 0.65rem",
              maxWidth: "16ch",
            }}
          >
            FarmOps
          </h1>
          <p style={{ margin: 0, maxWidth: 520, color: "var(--muted)", fontSize: "1.05rem", lineHeight: 1.5 }}>
            {verdict.detail}
            {pendingApprovals > 0
              ? ` Có ${pendingApprovals} lệnh đang chờ phê duyệt trên trang Giao tiếp với AI.`
              : ""}
          </p>
        </div>

        <div className="metric-row" aria-label="Chỉ số chính">
          <article>
            <div className="label">Độ ẩm đất</div>
            <div className="value">{soil != null ? `${soil}%` : "--"}</div>
          </article>
          <article>
            <div className="label">Nhiệt độ KK</div>
            <div className="value">{weather != null ? `${weather}°C` : "--"}</div>
          </article>
          <article>
            <div className="label">Bồn nước</div>
            <div className="value">{tank != null ? `${tank}%` : "--"}</div>
          </article>
          <article>
            <div className="label">Bơm</div>
            <div className="value">{pump != null ? `${pump} L/ph` : "--"}</div>
          </article>
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "center" }}>
          <Link to="/chat" className="btn btn-primary" style={{ textDecoration: "none" }}>
            Giao tiếp với AI
          </Link>
          <Link to="/settings" className="btn btn-ghost" style={{ textDecoration: "none" }}>
            Cài đặt
          </Link>
        </div>
      </section>

      <SensorBoard devices={DEVICES} telemetry={telemetry} historyMap={historyMap} />
    </main>
  );
}
