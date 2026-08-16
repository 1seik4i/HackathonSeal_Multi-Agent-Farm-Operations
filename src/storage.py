from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from src.models import ActionRecord, TelemetryMessage


class FarmStore:
    def __init__(self, path: str = "farmops.db") -> None:
        self.path = Path(path)
        self._init_schema()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS telemetry (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  device_code TEXT NOT NULL,
                  timestamp REAL NOT NULL,
                  metrics_json TEXT NOT NULL,
                  received_at REAL NOT NULL,
                  source_type TEXT NOT NULL DEFAULT 'API',
                  topic TEXT,
                  payload_hash TEXT,
                  quality_json TEXT
                );
                CREATE INDEX IF NOT EXISTS telemetry_device_time ON telemetry(device_code, timestamp DESC);
                CREATE TABLE IF NOT EXISTS actions (
                  id TEXT PRIMARY KEY,
                  action_type TEXT NOT NULL,
                  status TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  created_at REAL NOT NULL,
                  updated_at REAL
                );
                CREATE TABLE IF NOT EXISTS coordination_runs (
                  id TEXT PRIMARY KEY,
                  status TEXT NOT NULL,
                  request_json TEXT NOT NULL,
                  result_json TEXT,
                  created_at REAL NOT NULL,
                  updated_at REAL NOT NULL
                );
                """
            )

            columns = {row["name"] for row in conn.execute("PRAGMA table_info(telemetry)")}
            for column, definition in [("source_type", "TEXT NOT NULL DEFAULT 'API'"), ("topic", "TEXT"), ("payload_hash", "TEXT"), ("quality_json", "TEXT")]:
                if column not in columns:
                    conn.execute(f"ALTER TABLE telemetry ADD COLUMN {column} {definition}")
            action_columns = {row["name"] for row in conn.execute("PRAGMA table_info(actions)")}
            if "updated_at" not in action_columns:
                conn.execute("ALTER TABLE actions ADD COLUMN updated_at REAL")

    def ingest(self, message: TelemetryMessage, source_type: str = "API", topic: str | None = None, raw_payload: str | None = None, quality: dict[str, Any] | None = None) -> None:
        if source_type not in {"MQTT", "DEMO", "API"}:
            raise ValueError("unsupported telemetry source")
        payload_hash = hashlib.sha256(raw_payload.encode("utf-8")).hexdigest() if raw_payload else None
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO telemetry(device_code,timestamp,metrics_json,received_at,source_type,topic,payload_hash,quality_json) VALUES(?,?,?,?,?,?,?,?)",
                (message.device_code, message.timestamp, json.dumps(message.metrics), time.time(), source_type, topic, payload_hash, json.dumps(quality) if quality else None),
            )

    def latest_by_device(self) -> dict[str, dict[str, Any]]:
        query = """
          SELECT t.device_code,t.timestamp,t.metrics_json,t.received_at,t.source_type,t.topic,t.payload_hash,t.quality_json
          FROM telemetry t JOIN (
             SELECT device_code, MAX(id) latest FROM telemetry GROUP BY device_code
          ) newest ON newest.device_code=t.device_code AND newest.latest=t.id
        """
        with self._connect() as conn:
            return {
                row["device_code"]: {"timestamp": row["timestamp"], "metrics": json.loads(row["metrics_json"]), "received_at": row["received_at"], "source_type": row["source_type"], "topic": row["topic"], "payload_hash": row["payload_hash"], "quality": json.loads(row["quality_json"]) if row["quality_json"] else None}
                for row in conn.execute(query)
            }

    def create_action(self, action_type: str, status: str, payload: dict[str, Any]) -> ActionRecord:
        now = time.time()
        record = ActionRecord(
            id=f"{action_type[:3]}-{uuid.uuid4().hex[:8].upper()}",
            action_type=action_type,
            status=status,
            payload=payload,
            created_at=now, updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO actions(id,action_type,status,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (record.id, record.action_type, record.status, json.dumps(record.payload), record.created_at, record.updated_at),
            )
        return record

    def get_action(self, action_id: str) -> ActionRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
        if row is None:
            return None
        return ActionRecord(
            id=row["id"], action_type=row["action_type"], status=row["status"],
            payload=json.loads(row["payload_json"]), created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def list_actions(self, limit: int = 50) -> list[ActionRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM actions ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [ActionRecord(id=row["id"], action_type=row["action_type"], status=row["status"], payload=json.loads(row["payload_json"]), created_at=row["created_at"], updated_at=row["updated_at"]) for row in rows]

    def update_action(self, action_id: str, status: str, payload_updates: dict[str, Any] | None = None) -> ActionRecord | None:
        action = self.get_action(action_id)
        if action is None:
            return None
        payload = action.payload | (payload_updates or {})
        now = time.time()
        with self._connect() as conn:
            conn.execute("UPDATE actions SET status=?,payload_json=?,updated_at=? WHERE id=?", (status, json.dumps(payload), now, action_id))
        return self.get_action(action_id)

    def latest_after(self, device_code: str, received_after: float) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM telemetry WHERE device_code=? AND received_at>? ORDER BY id DESC LIMIT 1", (device_code, received_after)).fetchone()
        if row is None:
            return None
        return {"timestamp": row["timestamp"], "received_at": row["received_at"], "metrics": json.loads(row["metrics_json"]), "source_type": row["source_type"], "quality": json.loads(row["quality_json"]) if row["quality_json"] else None}

    def telemetry_history(self, device_code: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT device_code,timestamp,metrics_json,received_at,source_type,topic,quality_json FROM telemetry WHERE device_code=? ORDER BY id DESC LIMIT ?", (device_code, limit)).fetchall()
        return [{"device_code": row["device_code"], "timestamp": row["timestamp"], "metrics": json.loads(row["metrics_json"]), "received_at": row["received_at"], "source_type": row["source_type"], "topic": row["topic"], "quality": json.loads(row["quality_json"]) if row["quality_json"] else None} for row in rows]

    def telemetry_history_window(self, device_code: str, since: float, points: int = 30) -> list[dict[str, Any]]:
        """Return one real reading per time bucket without inventing data."""
        window_seconds = max(1.0, time.time() - since)
        bucket_seconds = max(1.0, window_seconds / points)
        query = """
          WITH sampled AS (
            SELECT MAX(id) AS id
            FROM telemetry
            WHERE device_code=? AND timestamp>=?
            GROUP BY CAST((timestamp - ?) / ? AS INTEGER)
          )
          SELECT t.device_code,t.timestamp,t.metrics_json,t.received_at,t.source_type,t.topic,t.quality_json
          FROM telemetry t JOIN sampled s ON s.id=t.id
          ORDER BY t.timestamp DESC
        """
        with self._connect() as conn:
            rows = conn.execute(query, (device_code, since, since, bucket_seconds)).fetchall()
        return [{"device_code": row["device_code"], "timestamp": row["timestamp"], "metrics": json.loads(row["metrics_json"]), "received_at": row["received_at"], "source_type": row["source_type"], "topic": row["topic"], "quality": json.loads(row["quality_json"]) if row["quality_json"] else None} for row in rows]

    def create_run(self, request: dict[str, Any]) -> str:
        run_id = f"RUN-{uuid.uuid4().hex[:10].upper()}"
        now = time.time()
        with self._connect() as conn:
            conn.execute("INSERT INTO coordination_runs(id,status,request_json,created_at,updated_at) VALUES(?,?,?,?,?)", (run_id, "RUNNING", json.dumps(request), now, now))
        return run_id

    def complete_run(self, run_id: str, status: str, result: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE coordination_runs SET status=?,result_json=?,updated_at=? WHERE id=?", (status, json.dumps(result), time.time(), run_id))

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM coordination_runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            return None
        return {"run_id": row["id"], "status": row["status"], "request": json.loads(row["request_json"]), "result": json.loads(row["result_json"]) if row["result_json"] else None, "created_at": row["created_at"], "updated_at": row["updated_at"]}
