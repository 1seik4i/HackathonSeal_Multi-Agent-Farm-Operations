/**
 * Data Processing Pipeline for IoT telemetry.
 * Ported to ES Modules for Node.js Backend.
 */

export const SENSOR_RANGES = {
  SOIL_01: {
    soil_moisture: [0, 100], // %
    temperature: [-10, 60], // °C
  },
  WEATHER_01: {
    temperature: [-20, 55], // °C
    humidity: [0, 100], // %
  },
  PUMP_01: {
    flow_rate: [0, 200], // L/min
    power: [0, 5000], // W
  },
  PH_01: {
    ph: [0, 14],
  },
  TANK_01: {
    level: [0, 100], // %
  },
  SUN_01: {
    lux: [0, 150000], // lux
  },
};

export const VALID_DEVICES = new Set(Object.keys(SENSOR_RANGES));
const DEFAULT_STALE_SECONDS = 300;

export class IoTDataProcessor {
  constructor(staleAfterSeconds = DEFAULT_STALE_SECONDS) {
    this.staleAfterSeconds = staleAfterSeconds;
  }

  validatePayload(raw) {
    const errors = [];
    const device = raw?.device_code;
    if (!device) {
      errors.push("Missing device_code");
    } else if (!VALID_DEVICES.has(device)) {
      errors.push(`Unknown device_code: ${device}`);
    }

    const metrics = raw?.metrics;
    if (!metrics || typeof metrics !== "object" || Object.keys(metrics).length === 0) {
      errors.push("metrics must be a non-empty object");
    }

    const ts = raw?.timestamp;
    if (ts !== undefined && ts !== null) {
      if (typeof ts !== "number" || ts < 0) {
        errors.push("timestamp must be non-negative number");
      }
    }
    return errors;
  }

  checkRanges(deviceCode, metrics) {
    const ranges = SENSOR_RANGES[deviceCode] || {};
    const valid = [];
    const outOfRange = [];

    for (const [metric, value] of Object.entries(metrics)) {
      const bounds = ranges[metric];
      const entry = { metric, value };
      if (!bounds) {
        valid.push(entry);
        continue;
      }
      const [lo, hi] = bounds;
      entry.min = lo;
      entry.max = hi;
      if (value >= lo && value <= hi) {
        valid.push(entry);
      } else {
        outOfRange.push(entry);
      }
    }
    return { valid, outOfRange };
  }

  computeFreshness(timestamp) {
    if (timestamp === undefined || timestamp === null) return "MISSING";
    const age = Date.now() / 1000 - timestamp;
    return age < this.staleAfterSeconds + 0.5 ? "FRESH" : "STALE";
  }

  detectAnomalies(deviceCode, metrics) {
    const anomalies = [];
    const warningThresholds = {
      SOIL_01: { soil_moisture: [10, 90], temperature: [0, 50] },
      WEATHER_01: { temperature: [-10, 50], humidity: [10, 95] },
      PUMP_01: { flow_rate: [1, 150], power: [50, 4000] },
      PH_01: { ph: [4, 10] },
      TANK_01: { level: [5, 95] },
      SUN_01: { lux: [0, 120000] },
    };

    const thresholds = warningThresholds[deviceCode] || {};
    for (const [metric, value] of Object.entries(metrics)) {
      const bounds = thresholds[metric];
      if (!bounds) continue;
      const [lo, hi] = bounds;
      if (value < lo || value > hi) {
        anomalies.push({
          metric,
          value,
          expected_min: lo,
          expected_max: hi,
          severity: "WARNING",
        });
      }
    }
    return anomalies;
  }

  process(rawPayload) {
    const errors = this.validatePayload(rawPayload);
    if (errors.length > 0) {
      throw new Error(`Invalid payload: ${errors.join("; ")}`);
    }

    const deviceCode = rawPayload.device_code;
    const metrics = rawPayload.metrics;
    const timestamp = rawPayload.timestamp || Date.now() / 1000;

    const rangeResult = this.checkRanges(deviceCode, metrics);
    const outOfRange = rangeResult.outOfRange;
    const freshness = this.computeFreshness(timestamp);
    const anomalies = this.detectAnomalies(deviceCode, metrics);

    const cleanedMetrics = { ...metrics };
    const ranges = SENSOR_RANGES[deviceCode] || {};
    for (const item of outOfRange) {
      const m = item.metric;
      const bounds = ranges[m] || [item.value, item.value];
      cleanedMetrics[m] = Math.max(bounds[0], Math.min(bounds[1], metrics[m]));
    }

    const isValid = errors.length === 0 && outOfRange.length === 0;
    return {
      device_code: deviceCode,
      timestamp,
      metrics: cleanedMetrics,
      quality: {
        freshness,
        anomalies,
        out_of_range: outOfRange,
        valid: isValid,
      },
      received_at: Date.now() / 1000,
      raw_payload: rawPayload,
    };
  }
}
