import os
import time
import unittest
import uuid
from pathlib import Path

from src.agents import FarmCoordinatorAgent
from src.models import TelemetryMessage
from src.storage import FarmStore


def message(device_code, metrics):
    return TelemetryMessage(device_code=device_code, timestamp=time.time(), metrics=metrics)


class FarmOpsTests(unittest.TestCase):
    def setUp(self):
        self.db_path = Path(__file__).parent / f"_test_{uuid.uuid4().hex}.db"
        self.store = FarmStore(str(self.db_path))
        self.agent = FarmCoordinatorAgent(self.store)

    def tearDown(self):
        if self.db_path.exists():
            os.unlink(self.db_path)

    def test_creates_verified_plan_when_resources_ready(self):
        readings = [
            message("SOIL_01", {"soil_moisture": 27, "temperature": 31}),
            message("WEATHER_01", {"temperature": 35, "humidity": 48}),
            message("PUMP_01", {"flow_rate": 18, "power": 430}),
            message("PH_01", {"ph": 6.4}),
            message("TANK_01", {"level": 62}),
            message("SUN_01", {"lux": 78000}),
        ]
        for item in readings: self.store.ingest(item)
        result = self.agent.handle("Lập kế hoạch tưới", "Manager")
        action = result["agent_trace"][-1]["verification"]
        self.assertEqual(action["action_type"], "IRRIGATION_PLAN")
        self.assertEqual(action["status"], "VERIFIED")

    def test_stale_soil_creates_field_task_without_fabrication(self):
        self.store.ingest(TelemetryMessage(device_code="SOIL_01", timestamp=time.time() - 9999, metrics={"soil_moisture": 10, "temperature": 30}))
        result = self.agent.handle("Lập kế hoạch tưới", "Manager")
        action = result["agent_trace"][-1]["verification"]
        self.assertEqual(action["action_type"], "FIELD_TASK")
        self.assertEqual(action["status"], "VERIFIED")
