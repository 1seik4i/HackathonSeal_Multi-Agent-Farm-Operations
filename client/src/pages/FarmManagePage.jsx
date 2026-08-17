import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useFarmData } from "../context/FarmDataContext";

const PLOT_COLORS = ["#7cb389", "#6a9f8a", "#8fbc8f", "#5f8f72", "#9cc5a1"];
const SENSOR_TIMEOUT_SEC = 200;

const DEVICE_LABELS = {
  SOIL_01: "Độ ẩm / nhiệt đất",
  WEATHER_01: "Thời tiết",
  SUN_01: "Ánh sáng",
  PUMP_01: "Máy bơm",
  PH_01: "pH đất",
  TANK_01: "Bồn nước",
};

function uid(prefix) {
  return `${prefix}_${Math.random().toString(16).slice(2, 8)}`;
}

function defaultRect(offset = 0) {
  const o = offset % 30;
  return [
    { x: 15 + o, y: 18 + o },
    { x: 40 + o, y: 16 + o },
    { x: 45 + o, y: 42 + o },
    { x: 18 + o, y: 46 + o },
  ];
}

function pointsToPath(points) {
  if (!points?.length) return "";
  return points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ") + " Z";
}

function getSensorLiveStatus(code, telemetry, nowSec = Date.now() / 1000) {
  const reading = telemetry?.[code];
  if (!reading) {
    return { alive: false, ageSec: null, label: "Không có dữ liệu" };
  }
  const ts = reading.received_at || reading.timestamp;
  if (!ts) {
    return { alive: false, ageSec: null, label: "Không có timestamp" };
  }
  const ageSec = Math.max(0, nowSec - ts);
  if (ageSec > SENSOR_TIMEOUT_SEC) {
    return {
      alive: false,
      ageSec: Math.round(ageSec),
      label: `Mất tín hiệu ${Math.round(ageSec)}s`,
    };
  }
  return {
    alive: true,
    ageSec: Math.round(ageSec),
    label: `Live · ${Math.round(ageSec)}s trước`,
  };
}

export function FarmManagePage() {
  const { DEVICES, telemetry } = useFarmData();
  const svgRef = useRef(null);
  const [plots, setPlots] = useState([]);
  const [sensors, setSensors] = useState([]);
  const [selectedPlotId, setSelectedPlotId] = useState(null);
  const [selectedSensorId, setSelectedSensorId] = useState(null);
  const [plotName, setPlotName] = useState("");
  const [sensorName, setSensorName] = useState("");
  const [sensorCode, setSensorCode] = useState("SOIL_01");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [nowTick, setNowTick] = useState(Date.now() / 1000);

  const dragRef = useRef(null);

  const selectedPlot = useMemo(
    () => plots.find((p) => p.id === selectedPlotId) || null,
    [plots, selectedPlotId]
  );

  useEffect(() => {
    const t = setInterval(() => setNowTick(Date.now() / 1000), 2000);
    return () => clearInterval(t);
  }, []);

  const sensorStatusMap = useMemo(() => {
    const map = {};
    for (const s of sensors) {
      map[s.id] = getSensorLiveStatus(s.code, telemetry, nowTick);
    }
    return map;
  }, [sensors, telemetry, nowTick]);

  const offlineCount = useMemo(
    () => Object.values(sensorStatusMap).filter((s) => !s.alive).length,
    [sensorStatusMap]
  );

  const loadMap = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await fetch("/api/farm-map");
      if (resp.ok) {
        const data = await resp.json();
        setPlots(data.plots || []);
        setSensors(data.sensors || []);
        if (data.plots?.[0]) setSelectedPlotId(data.plots[0].id);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadMap();
  }, [loadMap]);

  useEffect(() => {
    if (selectedPlot) setPlotName(selectedPlot.name || "");
  }, [selectedPlot]);

  const clientToPct = (clientX, clientY) => {
    const svg = svgRef.current;
    if (!svg) return { x: 50, y: 50 };
    const rect = svg.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(100, ((clientX - rect.left) / rect.width) * 100)),
      y: Math.max(0, Math.min(100, ((clientY - rect.top) / rect.height) * 100)),
    };
  };

  const addPlot = () => {
    const name = plotName.trim() || `Ô đất ${plots.length + 1}`;
    const id = uid("plot");
    const plot = {
      id,
      name,
      color: PLOT_COLORS[plots.length % PLOT_COLORS.length],
      points: defaultRect(plots.length * 8),
    };
    setPlots((prev) => [...prev, plot]);
    setSelectedPlotId(id);
    setSelectedSensorId(null);
    setMessage(`Đã thêm ô đất "${name}". Kéo đỉnh để chỉnh hình.`);
  };

  const addSensor = () => {
    const code = sensorCode.trim().toUpperCase();
    if (!DEVICES.includes(code)) {
      setMessage("Mã cảm biến phải chọn từ danh sách thiết bị đang có.");
      return;
    }
    if (sensors.some((s) => s.code === code)) {
      setMessage(`Cảm biến ${code} đã được gắn trên bản đồ.`);
      return;
    }
    const name = sensorName.trim() || DEVICE_LABELS[code] || code;
    const id = uid("sensor");
    const center = selectedPlot
      ? {
          x: selectedPlot.points.reduce((s, p) => s + p.x, 0) / selectedPlot.points.length,
          y: selectedPlot.points.reduce((s, p) => s + p.y, 0) / selectedPlot.points.length,
        }
      : { x: 50, y: 50 };

    setSensors((prev) => [
      ...prev,
      {
        id,
        name,
        code,
        x: center.x,
        y: center.y,
        plot_id: selectedPlotId,
      },
    ]);
    setSelectedSensorId(id);
    setMessage(`Đã liên kết cảm biến ${code}. Đỏ = không phản hồi > ${SENSOR_TIMEOUT_SEC}s.`);
    setSensorName("");
  };

  const deleteSelectedPlot = () => {
    if (!selectedPlotId) return;
    setPlots((prev) => prev.filter((p) => p.id !== selectedPlotId));
    setSensors((prev) => prev.filter((s) => s.plot_id !== selectedPlotId));
    setSelectedPlotId(null);
    setMessage("Đã xóa ô đất đã chọn.");
  };

  const deleteSelectedSensor = () => {
    if (!selectedSensorId) return;
    setSensors((prev) => prev.filter((s) => s.id !== selectedSensorId));
    setSelectedSensorId(null);
    setMessage("Đã xóa cảm biến đã chọn.");
  };

  const addVertex = () => {
    if (!selectedPlot) return;
    const pts = selectedPlot.points;
    const mid = {
      x: (pts[0].x + pts[1].x) / 2,
      y: (pts[0].y + pts[1].y) / 2,
    };
    setPlots((prev) =>
      prev.map((p) => (p.id === selectedPlot.id ? { ...p, points: [pts[0], mid, ...pts.slice(1)] } : p))
    );
    setMessage("Đã thêm điểm chỉnh hình. Kéo đỉnh mới để tạo hình thù mong muốn.");
  };

  const renameSelectedPlot = () => {
    if (!selectedPlotId || !plotName.trim()) return;
    setPlots((prev) => prev.map((p) => (p.id === selectedPlotId ? { ...p, name: plotName.trim() } : p)));
  };

  const saveMap = async () => {
    setSaving(true);
    setMessage("");
    try {
      if (selectedPlotId && plotName.trim()) {
        renameSelectedPlot();
      }
      const payload = {
        plots: plots.map((p) =>
          p.id === selectedPlotId && plotName.trim() ? { ...p, name: plotName.trim() } : p
        ),
        sensors,
      };
      const resp = await fetch("/api/farm-map", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (resp.ok) {
        const data = await resp.json();
        setPlots(data.plots || []);
        setSensors(data.sensors || []);
        setMessage("Đã lưu bản đồ nông trại.");
      } else {
        setMessage("Lưu thất bại.");
      }
    } finally {
      setSaving(false);
    }
  };

  const onPointerMove = (e) => {
    const drag = dragRef.current;
    if (!drag) return;
    const pos = clientToPct(e.clientX, e.clientY);

    if (drag.type === "vertex") {
      setPlots((prev) =>
        prev.map((p) => {
          if (p.id !== drag.plotId) return p;
          const points = p.points.map((pt, i) => (i === drag.vertexIndex ? { x: pos.x, y: pos.y } : pt));
          return { ...p, points };
        })
      );
    } else if (drag.type === "plot") {
      const dx = pos.x - drag.origin.x;
      const dy = pos.y - drag.origin.y;
      setPlots((prev) =>
        prev.map((p) => {
          if (p.id !== drag.plotId) return p;
          return {
            ...p,
            points: drag.basePoints.map((pt) => ({
              x: Math.max(0, Math.min(100, pt.x + dx)),
              y: Math.max(0, Math.min(100, pt.y + dy)),
            })),
          };
        })
      );
    } else if (drag.type === "sensor") {
      setSensors((prev) =>
        prev.map((s) => (s.id === drag.sensorId ? { ...s, x: pos.x, y: pos.y } : s))
      );
    }
  };

  const endDrag = () => {
    dragRef.current = null;
  };

  useEffect(() => {
    const up = () => endDrag();
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
    return () => {
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
    };
  }, []);

  return (
    <main>
      <h1 className="section-title" style={{ fontSize: "1.55rem" }}>
        Quản lý nông trại
      </h1>
      <p className="section-sub">
        Cảm biến gắn với thiết bị thật ({DEVICES.join(", ")}). Vòng tròn đỏ nếu không phản hồi trong{" "}
        {SENSOR_TIMEOUT_SEC}s
        {offlineCount > 0 ? ` — đang có ${offlineCount} cảm biến mất tín hiệu.` : "."}
      </p>

      <div className="farm-layout">
        <div className="farm-canvas-wrap">
          {loading ? (
            <div className="farm-empty">Đang tải bản đồ...</div>
          ) : (
            <svg
              ref={svgRef}
              className="farm-canvas"
              viewBox="0 0 100 100"
              preserveAspectRatio="none"
              onPointerMove={onPointerMove}
              onPointerLeave={endDrag}
            >
              <defs>
                <pattern id="farm-grid" width="5" height="5" patternUnits="userSpaceOnUse">
                  <path d="M 5 0 L 0 0 0 5" fill="none" stroke="rgba(20,36,28,0.06)" strokeWidth="0.15" />
                </pattern>
              </defs>
              <rect x="0" y="0" width="100" height="100" fill="url(#farm-grid)" />

              {plots.map((plot) => (
                <g key={plot.id}>
                  <path
                    d={pointsToPath(plot.points)}
                    fill={plot.color}
                    fillOpacity={selectedPlotId === plot.id ? 0.55 : 0.35}
                    stroke={selectedPlotId === plot.id ? "#14532d" : "#3f6b52"}
                    strokeWidth={selectedPlotId === plot.id ? 0.7 : 0.4}
                    style={{ cursor: "move" }}
                    onPointerDown={(e) => {
                      e.stopPropagation();
                      setSelectedPlotId(plot.id);
                      setSelectedSensorId(null);
                      const origin = clientToPct(e.clientX, e.clientY);
                      dragRef.current = {
                        type: "plot",
                        plotId: plot.id,
                        origin,
                        basePoints: plot.points.map((p) => ({ ...p })),
                      };
                      e.currentTarget.setPointerCapture?.(e.pointerId);
                    }}
                  />
                  <text
                    x={plot.points.reduce((s, p) => s + p.x, 0) / plot.points.length}
                    y={plot.points.reduce((s, p) => s + p.y, 0) / plot.points.length}
                    textAnchor="middle"
                    dominantBaseline="middle"
                    fontSize="2.4"
                    fill="#143528"
                    fontWeight="700"
                    style={{ pointerEvents: "none", userSelect: "none" }}
                  >
                    {plot.name}
                  </text>

                  {selectedPlotId === plot.id &&
                    plot.points.map((pt, idx) => (
                      <circle
                        key={`${plot.id}-v-${idx}`}
                        cx={pt.x}
                        cy={pt.y}
                        r="1.4"
                        fill="#fff"
                        stroke="#14532d"
                        strokeWidth="0.45"
                        style={{ cursor: "grab" }}
                        onPointerDown={(e) => {
                          e.stopPropagation();
                          dragRef.current = {
                            type: "vertex",
                            plotId: plot.id,
                            vertexIndex: idx,
                          };
                          e.currentTarget.setPointerCapture?.(e.pointerId);
                        }}
                      />
                    ))}
                </g>
              ))}

              {sensors.map((sensor) => {
                const status = sensorStatusMap[sensor.id] || { alive: false };
                const fill = status.alive
                  ? selectedSensorId === sensor.id
                    ? "#1f6b45"
                    : "#245c3d"
                  : selectedSensorId === sensor.id
                    ? "#b42318"
                    : "#dc2626";
                return (
                  <g
                    key={sensor.id}
                    style={{ cursor: "grab" }}
                    onPointerDown={(e) => {
                      e.stopPropagation();
                      setSelectedSensorId(sensor.id);
                      dragRef.current = { type: "sensor", sensorId: sensor.id };
                      e.currentTarget.setPointerCapture?.(e.pointerId);
                    }}
                  >
                    {!status.alive && (
                      <circle
                        cx={sensor.x}
                        cy={sensor.y}
                        r="3.4"
                        fill="none"
                        stroke="#dc2626"
                        strokeWidth="0.35"
                        opacity="0.55"
                      >
                        <animate attributeName="r" values="2.6;3.8;2.6" dur="1.6s" repeatCount="indefinite" />
                        <animate attributeName="opacity" values="0.7;0.15;0.7" dur="1.6s" repeatCount="indefinite" />
                      </circle>
                    )}
                    <circle
                      cx={sensor.x}
                      cy={sensor.y}
                      r="2.2"
                      fill={fill}
                      stroke="#fff"
                      strokeWidth="0.45"
                    />
                    <text
                      x={sensor.x}
                      y={sensor.y + 4.2}
                      textAnchor="middle"
                      fontSize="1.8"
                      fill={status.alive ? "#1a2e24" : "#b42318"}
                      fontWeight="600"
                      style={{ pointerEvents: "none" }}
                    >
                      {sensor.code || sensor.name}
                    </text>
                  </g>
                );
              })}
            </svg>
          )}
        </div>

        <aside className="farm-side">
          <h2 className="section-title">Chức năng</h2>

          <div className="field">
            <label htmlFor="plot-name">Tên ô đất</label>
            <input
              id="plot-name"
              value={plotName}
              onChange={(e) => setPlotName(e.target.value)}
              placeholder="Ví dụ: Khu A"
            />
          </div>
          <div className="farm-actions">
            <button type="button" className="btn btn-primary" onClick={addPlot}>
              Thêm ô đất
            </button>
            <button type="button" className="btn btn-ghost" onClick={renameSelectedPlot} disabled={!selectedPlotId}>
              Đổi tên ô
            </button>
            <button type="button" className="btn btn-ghost" onClick={addVertex} disabled={!selectedPlotId}>
              Thêm điểm hình
            </button>
            <button type="button" className="btn btn-danger" onClick={deleteSelectedPlot} disabled={!selectedPlotId}>
              Xóa ô đất
            </button>
          </div>

          <hr className="farm-divider" />

          <div className="field">
            <label htmlFor="sensor-code">Mã cảm biến (liên kết thiết bị)</label>
            <select id="sensor-code" value={sensorCode} onChange={(e) => setSensorCode(e.target.value)}>
              {DEVICES.map((code) => (
                <option key={code} value={code} disabled={sensors.some((s) => s.code === code)}>
                  {code} — {DEVICE_LABELS[code] || code}
                  {sensors.some((s) => s.code === code) ? " (đã gắn)" : ""}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="sensor-name">Tên cảm biến</label>
            <input
              id="sensor-name"
              value={sensorName}
              onChange={(e) => setSensorName(e.target.value)}
              placeholder={DEVICE_LABELS[sensorCode] || "Tên hiển thị"}
            />
          </div>
          <div className="farm-actions">
            <button type="button" className="btn btn-primary" onClick={addSensor}>
              Thêm cảm biến
            </button>
            <button type="button" className="btn btn-danger" onClick={deleteSelectedSensor} disabled={!selectedSensorId}>
              Xóa cảm biến
            </button>
          </div>

          <div className="farm-sensor-status">
            <div className="farm-legend">
              <span>
                <i className="dot live" /> Live ≤ {SENSOR_TIMEOUT_SEC}s
              </span>
              <span>
                <i className="dot dead" /> Mất tín hiệu
              </span>
            </div>
            {sensors.length === 0 ? (
              <p style={{ color: "var(--muted)", fontSize: "0.92rem" }}>Chưa gắn cảm biến nào.</p>
            ) : (
              sensors.map((s) => {
                const st = sensorStatusMap[s.id];
                return (
                  <button
                    key={s.id}
                    type="button"
                    className={`farm-sensor-row ${selectedSensorId === s.id ? "active" : ""} ${st?.alive ? "ok" : "bad"}`}
                    onClick={() => setSelectedSensorId(s.id)}
                  >
                    <strong>{s.code}</strong>
                    <span>{st?.label || "—"}</span>
                  </button>
                );
              })
            )}
          </div>

          <hr className="farm-divider" />

          <button type="button" className="btn btn-primary" style={{ width: "100%" }} disabled={saving} onClick={saveMap}>
            {saving ? "Đang lưu..." : "Lưu"}
          </button>

          {message && <p className="farm-msg">{message}</p>}

          <div className="farm-hint">
            <p>
              <strong>Hướng dẫn:</strong> chọn ô đất → kéo các chấm trắng để đổi hình; kéo thân ô để dịch chuyển; kéo
              vòng tròn cảm biến để đặt vị trí; bấm <em>Thêm điểm hình</em> để có nhiều đỉnh hơn.
            </p>
          </div>
        </aside>
      </div>
    </main>
  );
}
