import os
import time
import unittest
import uuid
from pathlib import Path

from src.agents import FarmCoordinatorAgent
from src.models import TelemetryMessage
from src.storage import FarmStore


class FarmOpsTests(unittest.TestCase):
    def setUp(self):
        self.db_path = Path(__file__).parent / f"_test_{uuid.uuid4().hex}.db"
        self.store = FarmStore(str(self.db_path))
        self.agent = FarmCoordinatorAgent(self.store)

    def tearDown(self):
        if self.db_path.exists():
            os.unlink(self.db_path)

    def _ingest_ready_farm(self, soil_moisture=27):
        readings = [
            TelemetryMessage(device_code="SOIL_01", timestamp=time.time(), metrics={"soil_moisture": soil_moisture, "temperature": 31}),
            TelemetryMessage(device_code="WEATHER_01", timestamp=time.time(), metrics={"temperature": 35, "humidity": 48}),
            TelemetryMessage(device_code="PUMP_01", timestamp=time.time(), metrics={"flow_rate": 18, "power": 430, "pump_status": 1}),
            TelemetryMessage(device_code="PH_01", timestamp=time.time(), metrics={"ph": 6.4}),
            TelemetryMessage(device_code="TANK_01", timestamp=time.time(), metrics={"level": 62}),
            TelemetryMessage(device_code="SUN_01", timestamp=time.time(), metrics={"lux": 78000}),
        ]
        for reading in readings:
            self.store.ingest(reading)

    def test_plan_requires_human_approval(self):
        self._ingest_ready_farm()
        result = self.agent.handle("Create an irrigation plan", "Manager")
        action = result["agent_trace"][-1]["created"]
        self.assertEqual(action["action_type"], "IRRIGATION_PLAN")
        self.assertEqual(action["status"], "PENDING_APPROVAL")
        self.assertEqual(action["payload"]["schedule"]["target_zone"], "Farm Zone 1")

    def test_sensor_older_than_timeout_creates_field_task(self):
        self.store.ingest(TelemetryMessage(device_code="SOIL_01", timestamp=time.time() - 61, metrics={"soil_moisture": 10, "temperature": 30}))
        result = self.agent.handle("Create an irrigation plan", "Manager")
        action = result["agent_trace"][-1]["created"]
        self.assertEqual(action["action_type"], "FIELD_TASK")
        self.assertEqual(action["status"], "CREATED")


if __name__ == "__main__":
    unittest.main()
