import { useEffect, useState } from "react";
import { useFarmData } from "../context/FarmDataContext";

const PRESETS = [
  "Hãy kiểm tra và lập kế hoạch tưới cho khu A hôm nay và giải thích dữ liệu.",
  "Hãy kiểm tra hoạt động các thiết bị bơm, bể chứa và nồng độ pH nguồn nước.",
  "Dữ liệu cảm biến vừa ngừng cập nhật. Hãy lập kế hoạch công việc cho đội ngoài hiện trường.",
];

export function ChatPage() {
  const {
    settingsBundle,
    loadingAgent,
    agentResult,
    agentHealth,
    actions,
    handleCoordinate,
    handleApproveAction,
    handleVerifyAction,
    handleClearActions,
  } = useFarmData();

  const settings = settingsBundle?.settings;
  const [requestText, setRequestText] = useState("");

  useEffect(() => {
    if (settings?.default_prompt) {
      setRequestText((prev) => prev || settings.default_prompt);
    }
  }, [settings]);

  const runAi = async () => {
    await handleCoordinate(requestText || settings?.default_prompt, settings?.manager_name);
  };

  return (
    <main className="panel-stack">
      <section>
        <h1 className="section-title" style={{ fontSize: "1.55rem" }}>
          Giao tiếp với AI
        </h1>
        <p className="section-sub">
          Gửi yêu cầu vận hành, xem đàm phán multi-agent và phê duyệt lệnh tưới.
        </p>

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
              Hệ thống đã truy xuất phát hiện <strong>{agentHealth.failed_agents.length} AI Agent gặp lỗi / không phản hồi</strong>:
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
              💡 <strong>Tự động Bảo vệ Hệ thống:</strong> Ngay khi phát hiện AI gặp sự cố, hệ thống đã chuyển sang sử dụng bộ mã thuần logic (kiểm tra độ ẩm đất thấp/cao, mực nước bồn thấp/cao, pH & bơm) để duy trì hoạt động nông nghiệp an toàn đến khi AI phục hồi!
            </div>
          </div>
        )}

        <div className="chip-row">
          {PRESETS.map((p) => (
            <button key={p} type="button" className="chip" onClick={() => setRequestText(p)}>
              {p.slice(0, 48)}…
            </button>
          ))}
        </div>

        <div className="field">
          <label htmlFor="run-prompt">Yêu cầu vận hành</label>
          <textarea id="run-prompt" value={requestText} onChange={(e) => setRequestText(e.target.value)} />
        </div>

        <button type="button" className="btn btn-primary" disabled={loadingAgent} onClick={runAi}>
          {loadingAgent ? "Đang đàm phán..." : "Khởi chạy AI"}
        </button>

        {agentResult && (
          <div style={{ marginTop: "1.5rem" }}>
            <h2 className="section-title">Báo cáo điều hành</h2>
            <p style={{ margin: "0 0 1rem", lineHeight: 1.65, fontSize: "1.02rem" }}>
              {agentResult.ai_executive_summary || agentResult.narrative_summary || "Không có tóm tắt."}
            </p>
            {(agentResult.agent_dialogue || []).length > 0 && (
              <div>
                <h3 style={{ margin: "0 0 0.4rem", fontSize: "1.02rem", fontWeight: 700 }}>Nhật ký đàm phán</h3>
                {(agentResult.agent_dialogue || []).map((item, idx) => (
                  <div className="dialogue-item" key={idx} style={{ borderLeft: item.status === "FAILED" ? "4px solid #dc2626" : "4px solid #16a34a" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <div style={{ fontWeight: 700, fontSize: "1rem" }}>{item.speaker} ({item.agent})</div>
                      <span
                        style={{
                          fontSize: "0.75rem",
                          fontWeight: 700,
                          padding: "0.15rem 0.5rem",
                          borderRadius: "999px",
                          backgroundColor: item.status === "FAILED" ? "#fef2f2" : "#f0fdf4",
                          color: item.status === "FAILED" ? "#dc2626" : "#166534",
                          border: item.status === "FAILED" ? "1px solid #fecaca" : "1px solid #bbf7d0",
                        }}
                      >
                        {item.status === "FAILED" ? "🔴 AGENT ERROR - FALLBACK LOGIC" : "🟢 ONLINE"}
                      </span>
                    </div>
                    <div style={{ fontSize: "0.88rem", color: "var(--muted)", marginBottom: 6 }}>{item.llm_model}</div>
                    <div style={{ lineHeight: 1.6, fontSize: "0.98rem" }}>{item.message}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </section>

      <section>
        <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", alignItems: "center" }}>
          <div>
            <h2 className="section-title">Lệnh & phê duyệt</h2>
            <p className="section-sub" style={{ marginBottom: 0 }}>
              Duyệt / từ chối / xác minh vật lý qua MQTT.
            </p>
          </div>
          <button type="button" className="btn btn-ghost" onClick={handleClearActions}>
            Xóa lịch sử
          </button>
        </div>

        {actions.length === 0 ? (
          <p style={{ color: "var(--muted)", fontSize: "1rem" }}>Chưa có lệnh. Hãy khởi chạy AI ở trên.</p>
        ) : (
          actions.map((act) => (
            <div className="action-item" key={act.id}>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", alignItems: "center" }}>
                <strong style={{ fontFamily: "ui-monospace, monospace", fontSize: "0.9rem" }}>{act.id}</strong>
                <span style={{ fontWeight: 700 }}>{act.action_type}</span>
                <span style={{ color: "var(--muted)", fontSize: "0.9rem" }}>{act.status}</span>
              </div>
              <div style={{ color: "var(--muted)", fontSize: "0.98rem", lineHeight: 1.5 }}>
                {act.payload?.reason || act.payload?.task || "Lệnh nông nghiệp"}
              </div>
              {act.payload?.schedule && (
                <div style={{ fontSize: "0.92rem" }}>
                  {act.payload.schedule.start_time || "17:30"} · {act.payload.schedule.duration_minutes || 20} phút ·{" "}
                  {act.payload.schedule.target_zone || settings?.target_zone || "Khu A"}
                </div>
              )}
              <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                {act.status === "PENDING_APPROVAL" && (
                  <>
                    <button type="button" className="btn btn-primary" onClick={() => handleApproveAction(act.id, "APPROVE")}>
                      Đồng ý
                    </button>
                    <button type="button" className="btn btn-danger" onClick={() => handleApproveAction(act.id, "REJECT")}>
                      Từ chối
                    </button>
                  </>
                )}
                {act.status === "APPROVED" && (
                  <button type="button" className="btn btn-warn" onClick={() => handleVerifyAction(act.id)}>
                    Xác minh bơm MQTT
                  </button>
                )}
              </div>
            </div>
          ))
        )}
      </section>
    </main>
  );
}
