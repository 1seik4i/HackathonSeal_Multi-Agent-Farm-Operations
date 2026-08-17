import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import crypto from "crypto";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FARM_MAP_PATH = path.join(__dirname, "../.farm-map.json");

const DEFAULT_MAP = {
  plots: [
    {
      id: "plot_demo_a",
      name: "Khu A",
      color: "#7cb389",
      points: [
        { x: 12, y: 18 },
        { x: 42, y: 14 },
        { x: 48, y: 48 },
        { x: 18, y: 55 },
      ],
    },
  ],
  sensors: [
    {
      id: "sensor_demo_1",
      name: "Cảm biến đất",
      code: "SOIL_01",
      x: 28,
      y: 32,
      plot_id: "plot_demo_a",
    },
  ],
};

function load() {
  try {
    if (fs.existsSync(FARM_MAP_PATH)) {
      const raw = JSON.parse(fs.readFileSync(FARM_MAP_PATH, "utf8"));
      return {
        plots: Array.isArray(raw.plots) ? raw.plots : [],
        sensors: Array.isArray(raw.sensors) ? raw.sensors : [],
      };
    }
  } catch {
    /* defaults */
  }
  return structuredClone(DEFAULT_MAP);
}

let state = load();

export function getFarmMap() {
  return structuredClone(state);
}

export function saveFarmMap(payload = {}) {
  const plots = Array.isArray(payload.plots) ? payload.plots : state.plots;
  const sensors = Array.isArray(payload.sensors) ? payload.sensors : state.sensors;

  state = {
    plots: plots.map((p) => ({
      id: p.id || `plot_${crypto.randomBytes(3).toString("hex")}`,
      name: String(p.name || "Ô đất").slice(0, 80),
      color: p.color || "#7cb389",
      points: (p.points || [])
        .map((pt) => ({
          x: Math.max(0, Math.min(100, Number(pt.x) || 0)),
          y: Math.max(0, Math.min(100, Number(pt.y) || 0)),
        }))
        .filter((_, i, arr) => arr.length >= 3),
    })).filter((p) => p.points.length >= 3),
    sensors: sensors.map((s) => ({
      id: s.id || `sensor_${crypto.randomBytes(3).toString("hex")}`,
      name: String(s.name || "Cảm biến").slice(0, 80),
      code: String(s.code || "").slice(0, 40),
      x: Math.max(0, Math.min(100, Number(s.x) || 50)),
      y: Math.max(0, Math.min(100, Number(s.y) || 50)),
      plot_id: s.plot_id || null,
    })),
  };

  try {
    fs.writeFileSync(FARM_MAP_PATH, JSON.stringify(state, null, 2), "utf8");
  } catch (err) {
    console.warn("[FarmMap] Persist failed:", err.message);
  }
  return getFarmMap();
}
