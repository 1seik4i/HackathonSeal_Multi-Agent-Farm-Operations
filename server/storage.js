import sqlite3 from "sqlite3";
import crypto from "crypto";

export class FarmStore {
  constructor(dbPath = "farmops.db") {
    this.db = new sqlite3.Database(dbPath);
    this._initTables();
  }

  _initTables() {
    this.db.serialize(() => {
      this.db.run(`
        CREATE TABLE IF NOT EXISTS telemetry (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          device_code TEXT NOT NULL,
          timestamp REAL NOT NULL,
          metrics_json TEXT NOT NULL,
          received_at REAL NOT NULL,
          source_type TEXT DEFAULT 'API',
          quality_json TEXT
        )
      `);
      this.db.run(`CREATE INDEX IF NOT EXISTS idx_telemetry_device_time ON telemetry(device_code, timestamp DESC)`);

      this.db.run(`
        CREATE TABLE IF NOT EXISTS actions (
          id TEXT PRIMARY KEY,
          action_type TEXT NOT NULL,
          status TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          created_at REAL NOT NULL,
          updated_at REAL
        )
      `);

      this.db.run(`
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY,
          scenario_text TEXT,
          status TEXT NOT NULL,
          result_json TEXT,
          created_at REAL NOT NULL
        )
      `);
    });
  }

  ingest(message, sourceType = "API", quality = null) {
    const now = Date.now() / 1000;
    const metricsJson = JSON.stringify(message.metrics);
    const qualityJson = quality ? JSON.stringify(quality) : null;
    const ts = message.timestamp || now;

    return new Promise((resolve, reject) => {
      this.db.run(
        `INSERT INTO telemetry (device_code, timestamp, metrics_json, received_at, source_type, quality_json)
         VALUES (?, ?, ?, ?, ?, ?)`,
        [message.device_code, ts, metricsJson, now, sourceType, qualityJson],
        function (err) {
          if (err) reject(err);
          else resolve(this.lastID);
        }
      );
    });
  }

  latestByDevice() {
    const devices = ["SOIL_01", "WEATHER_01", "PUMP_01", "PH_01", "TANK_01", "SUN_01"];
    const sql = `
      SELECT t1.* FROM telemetry t1
      INNER JOIN (
        SELECT device_code, MAX(timestamp) as max_ts
        FROM telemetry GROUP BY device_code
      ) t2 ON t1.device_code = t2.device_code AND t1.timestamp = t2.max_ts
    `;

    return new Promise((resolve, reject) => {
      this.db.all(sql, [], (err, rows) => {
        if (err) return reject(err);
        const result = {};
        for (const row of rows) {
          result[row.device_code] = {
            timestamp: row.timestamp,
            metrics: JSON.parse(row.metrics_json),
            received_at: row.received_at,
            source_type: row.source_type,
            quality: row.quality_json ? JSON.parse(row.quality_json) : null,
          };
        }
        resolve(result);
      });
    });
  }

  telemetryHistory(deviceCode, limit = 30) {
    const sql = `
      SELECT timestamp, metrics_json, received_at, source_type, quality_json
      FROM telemetry WHERE device_code = ?
      ORDER BY timestamp DESC LIMIT ?
    `;
    return new Promise((resolve, reject) => {
      this.db.all(sql, [deviceCode, limit], (err, rows) => {
        if (err) return reject(err);
        const list = rows.map((r) => ({
          device_code: deviceCode,
          timestamp: r.timestamp,
          metrics: JSON.parse(r.metrics_json),
          received_at: r.received_at,
          source_type: r.source_type,
          quality: r.quality_json ? JSON.parse(r.quality_json) : null,
        }));
        resolve(list.reverse());
      });
    });
  }

  telemetryHistoryWindow(deviceCode, minTs, points = 30) {
    const sql = `
      SELECT timestamp, metrics_json, received_at, source_type, quality_json
      FROM telemetry WHERE device_code = ? AND timestamp >= ?
      ORDER BY timestamp ASC LIMIT ?
    `;
    return new Promise((resolve, reject) => {
      this.db.all(sql, [deviceCode, minTs, points], (err, rows) => {
        if (err) return reject(err);
        const list = rows.map((r) => ({
          device_code: deviceCode,
          timestamp: r.timestamp,
          metrics: JSON.parse(r.metrics_json),
          received_at: r.received_at,
          source_type: r.source_type,
          quality: r.quality_json ? JSON.parse(r.quality_json) : null,
        }));
        resolve(list);
      });
    });
  }

  createAction(actionType, status, payload) {
    const id = `act_${crypto.randomBytes(4).toString("hex")}`;
    const now = Date.now() / 1000;
    const payloadJson = JSON.stringify(payload);

    return new Promise((resolve, reject) => {
      this.db.run(
        `INSERT INTO actions (id, action_type, status, payload_json, created_at, updated_at)
         VALUES (?, ?, ?, ?, ?, ?)`,
        [id, actionType, status, payloadJson, now, now],
        (err) => {
          if (err) reject(err);
          else resolve({ id, action_type: actionType, status, payload, created_at: now, updated_at: now });
        }
      );
    });
  }

  getAction(id) {
    return new Promise((resolve, reject) => {
      this.db.get(`SELECT * FROM actions WHERE id = ?`, [id], (err, row) => {
        if (err) return reject(err);
        if (!row) return resolve(null);
        resolve({
          id: row.id,
          action_type: row.action_type,
          status: row.status,
          payload: JSON.parse(row.payload_json),
          created_at: row.created_at,
          updated_at: row.updated_at,
        });
      });
    });
  }

  listActions(limit = 30) {
    return new Promise((resolve, reject) => {
      this.db.all(`SELECT * FROM actions ORDER BY created_at DESC LIMIT ?`, [limit], (err, rows) => {
        if (err) return reject(err);
        resolve(
          rows.map((row) => ({
            id: row.id,
            action_type: row.action_type,
            status: row.status,
            payload: JSON.parse(row.payload_json),
            created_at: row.created_at,
            updated_at: row.updated_at,
          }))
        );
      });
    });
  }

  clearActions() {
    return new Promise((resolve, reject) => {
      this.db.run(`DELETE FROM actions`, (err) => {
        if (err) reject(err);
        else resolve(true);
      });
    });
  }

  updateAction(id, status, extraPayload = {}) {
    return new Promise(async (resolve, reject) => {
      const existing = await this.getAction(id);
      if (!existing) return resolve(null);

      const now = Date.now() / 1000;
      const updatedPayload = { ...existing.payload, ...extraPayload };
      const payloadJson = JSON.stringify(updatedPayload);

      this.db.run(
        `UPDATE actions SET status = ?, payload_json = ?, updated_at = ? WHERE id = ?`,
        [status, payloadJson, now, id],
        (err) => {
          if (err) reject(err);
          else resolve({ id, action_type: existing.action_type, status, payload: updatedPayload, created_at: existing.created_at, updated_at: now });
        }
      );
    });
  }

  latestAfter(deviceCode, minTs) {
    return new Promise((resolve, reject) => {
      this.db.get(
        `SELECT * FROM telemetry WHERE device_code = ? AND timestamp >= ? ORDER BY timestamp DESC LIMIT 1`,
        [deviceCode, minTs],
        (err, row) => {
          if (err) return reject(err);
          if (!row) return resolve(null);
          resolve({
            device_code: row.device_code,
            timestamp: row.timestamp,
            metrics: JSON.parse(row.metrics_json),
            received_at: row.received_at,
            source_type: row.source_type,
            quality: row.quality_json ? JSON.parse(row.quality_json) : null,
          });
        }
      );
    });
  }

  createRun(runData) {
    const id = `run_${crypto.randomBytes(4).toString("hex")}`;
    const now = Date.now() / 1000;

    return new Promise((resolve, reject) => {
      this.db.run(
        `INSERT INTO runs (id, scenario_text, status, result_json, created_at) VALUES (?, ?, 'PENDING', null, ?)`,
        [id, runData.scenario_text || "", now],
        (err) => {
          if (err) reject(err);
          else resolve(id);
        }
      );
    });
  }

  completeRun(id, status, result) {
    const resultJson = JSON.stringify(result);
    return new Promise((resolve, reject) => {
      this.db.run(
        `UPDATE runs SET status = ?, result_json = ? WHERE id = ?`,
        [status, resultJson, id],
        (err) => {
          if (err) reject(err);
          else resolve(true);
        }
      );
    });
  }

  getRun(id) {
    return new Promise((resolve, reject) => {
      this.db.get(`SELECT * FROM runs WHERE id = ?`, [id], (err, row) => {
        if (err) return reject(err);
        if (!row) return resolve(null);
        resolve({
          id: row.id,
          scenario_text: row.scenario_text,
          status: row.status,
          result: row.result_json ? JSON.parse(row.result_json) : null,
          created_at: row.created_at,
        });
      });
    });
  }
}
