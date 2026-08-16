from __future__ import annotations

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
                  received_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS telemetry_device_time ON telemetry(device_code, timestamp DESC);
                CREATE TABLE IF NOT EXISTS actions (
                  id TEXT PRIMARY KEY,
                  action_type TEXT NOT NULL,
                  status TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  created_at REAL NOT NULL
                );
                """
            )

    def ingest(self, message: TelemetryMessage) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO telemetry(device_code,timestamp,metrics_json,received_at) VALUES(?,?,?,?)",
                (message.device_code, message.timestamp, json.dumps(message.metrics), time.time()),
            )

    def latest_by_device(self) -> dict[str, dict[str, Any]]:
        query = """
          SELECT t.device_code,t.timestamp,t.metrics_json
          FROM telemetry t JOIN (
             SELECT device_code, MAX(timestamp) latest FROM telemetry GROUP BY device_code
          ) newest ON newest.device_code=t.device_code AND newest.latest=t.timestamp
        """
        with self._connect() as conn:
            return {
                row["device_code"]: {"timestamp": row["timestamp"], "metrics": json.loads(row["metrics_json"])}
                for row in conn.execute(query)
            }

    def create_action(self, action_type: str, status: str, payload: dict[str, Any]) -> ActionRecord:
        record = ActionRecord(
            id=f"{action_type[:3]}-{uuid.uuid4().hex[:8].upper()}",
            action_type=action_type,
            status=status,
            payload=payload,
            created_at=time.time(),
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO actions(id,action_type,status,payload_json,created_at) VALUES(?,?,?,?,?)",
                (record.id, record.action_type, record.status, json.dumps(record.payload), record.created_at),
            )
        return record

    def get_action(self, action_id: str) -> ActionRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
        if row is None:
            return None
        return ActionRecord(
            id=row["id"], action_type=row["action_type"], status=row["status"],
            payload=json.loads(row["payload_json"]), created_at=row["created_at"],
        )

    def verify_action(self, action_id: str) -> ActionRecord | None:
        action = self.get_action(action_id)
        if action is None:
            return None
        with self._connect() as conn:
            conn.execute("UPDATE actions SET status='VERIFIED' WHERE id=?", (action_id,))
        return self.get_action(action_id)
