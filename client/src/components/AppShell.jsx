import { NavLink } from "react-router-dom";
import { useFarmData } from "../context/FarmDataContext";

export function AppShell({ children }) {
  const { systemStatus } = useFarmData();
  const online = systemStatus?.api_status === "online" || systemStatus?.api !== false;
  const mqtt = systemStatus?.mqtt_connected;

  return (
    <div className="app-shell">
      <header className="top-nav">
        <div>
          <div className="brand-font" style={{ fontSize: "1.45rem", fontWeight: 700 }}>
            FarmOps
          </div>
          <div style={{ fontSize: "0.9rem", color: "var(--muted)", marginTop: 2, lineHeight: 1.4 }}>
            <span className={`status-dot ${online ? "" : "off"}`} />{" "}
            {online ? "Hệ thống online" : "Mất kết nối API"}
            {" · "}
            {mqtt ? "MQTT live" : "Nguồn demo / API"}
          </div>
        </div>
        <nav className="nav-links" aria-label="Điều hướng">
          <NavLink to="/" end>
            Tổng quan
          </NavLink>
          <NavLink to="/farm">Quản lý nông trại</NavLink>
          <NavLink to="/chat">Giao tiếp với AI</NavLink>
          <NavLink to="/settings">Cài đặt</NavLink>
        </nav>
      </header>
      {children}
    </div>
  );
}
