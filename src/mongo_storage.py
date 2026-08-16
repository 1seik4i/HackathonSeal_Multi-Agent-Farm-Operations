"""MongoDB telemetry storage for IoT data.

TV1 — IoT & Data Engineer
Stores processed telemetry in MongoDB Atlas.  Completely independent
of ``storage.py`` (SQLite, owned by TV3).
"""

from __future__ import annotations

import logging
from typing import Any

from pymongo import DESCENDING, MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure

log = logging.getLogger(__name__)


class MongoTelemetryStore:
    """Manages the ``telemetry`` collection in MongoDB Atlas."""

    def __init__(self, uri: str, db_name: str = "farmops") -> None:
        self.client: MongoClient = MongoClient(uri, serverSelectionTimeoutMS=5000)
        self.db = self.client[db_name]
        self.telemetry = self.db["telemetry"]
        self._ensure_indexes()

    # ------------------------------------------------------------------
    # Indexes
    # ------------------------------------------------------------------
    def _ensure_indexes(self) -> None:
        """Create indexes for fast queries if they don't already exist."""
        try:
            self.telemetry.create_index(
                [("device_code", 1), ("timestamp", DESCENDING)],
                name="device_time_idx",
            )
            self.telemetry.create_index(
                [("received_at", DESCENDING)],
                name="received_idx",
            )
            log.info("MongoDB indexes ensured for telemetry collection")
        except OperationFailure as err:
            log.warning("Could not create MongoDB indexes: %s", err)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------
    def ingest(self, processed_data: dict[str, Any]) -> str:
        """Insert a processed telemetry document.

        Returns the string representation of the inserted ``_id``.
        """
        result = self.telemetry.insert_one(processed_data)
        log.info(
            "MongoDB: stored telemetry for %s (_id=%s)",
            processed_data.get("device_code"),
            result.inserted_id,
        )
        return str(result.inserted_id)

    # ------------------------------------------------------------------
    # Read — standardised output for TV2
    # ------------------------------------------------------------------
    def latest_by_device(self) -> dict[str, dict[str, Any]]:
        """Return the most recent processed document per device.

        Output format matches what TV2 ``FieldIoTAgent.observe()``
        expects: ``{device_code: {timestamp, metrics, quality}}``.
        """
        pipeline = [
            {"$sort": {"timestamp": -1}},
            {"$group": {
                "_id": "$device_code",
                "timestamp": {"$first": "$timestamp"},
                "metrics": {"$first": "$metrics"},
                "quality": {"$first": "$quality"},
            }},
        ]
        result: dict[str, dict[str, Any]] = {}
        for doc in self.telemetry.aggregate(pipeline):
            result[doc["_id"]] = {
                "timestamp": doc["timestamp"],
                "metrics": doc["metrics"],
                "quality": doc.get("quality"),
            }
        return result

    def get_history(
        self, device_code: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Return the ``limit`` most recent documents for a device."""
        cursor = (
            self.telemetry.find(
                {"device_code": device_code},
                {"_id": 0, "raw_payload": 0},
            )
            .sort("timestamp", DESCENDING)
            .limit(limit)
        )
        return list(cursor)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------
    def health_check(self) -> dict[str, Any]:
        """Ping the MongoDB server and return status info."""
        try:
            self.client.admin.command("ping")
            count = self.telemetry.estimated_document_count()
            return {"status": "ok", "documents": count}
        except ConnectionFailure as err:
            return {"status": "error", "error": str(err)}
