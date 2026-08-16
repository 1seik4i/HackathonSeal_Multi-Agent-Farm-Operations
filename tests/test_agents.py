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

    def test_stale_sensor(self):
        self.store.ingest(TelemetryMessage(device_code="SOIL_01", timestamp=time.time() - 9999, metrics={"soil_moisture": 20, "temperature": 30}))
        readings = [
            message("WEATHER_01", {"temperature": 35, "humidity": 48}),
            message("PUMP_01", {"flow_rate": 18, "power": 430}),
            message("PH_01", {"ph": 6.4}),
            message("TANK_01", {"level": 62}),
            message("SUN_01", {"lux": 78000}),
        ]
        for item in readings: self.store.ingest(item)
        result = self.agent.handle("Lập kế hoạch tưới", "Manager")
        action = result["agent_trace"][-1]["verification"]
        self.assertEqual(action["action_type"], "FIELD_TASK")
        self.assertEqual(action["status"], "VERIFIED")
        self.assertEqual(action["payload"]["reason"], "SENSOR_DATA_STALE")

    def test_missing_sensor(self):
        readings = [
            message("WEATHER_01", {"temperature": 35, "humidity": 48}),
            message("PUMP_01", {"flow_rate": 18, "power": 430}),
            message("PH_01", {"ph": 6.4}),
            message("TANK_01", {"level": 62}),
            message("SUN_01", {"lux": 78000}),
        ]
        for item in readings: self.store.ingest(item)
        result = self.agent.handle("Lập kế hoạch tưới", "Manager")
        action = result["agent_trace"][-1]["verification"]
        self.assertEqual(action["action_type"], "FIELD_TASK")
        self.assertEqual(action["payload"]["reason"], "SENSOR_DATA_MISSING")

    def test_low_soil_moisture(self):
        readings = [
            message("SOIL_01", {"soil_moisture": 30, "temperature": 31}),
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

    def test_insufficient_water(self):
        readings = [
            message("SOIL_01", {"soil_moisture": 20, "temperature": 31}),
            message("WEATHER_01", {"temperature": 35, "humidity": 48}),
            message("PUMP_01", {"flow_rate": 18, "power": 430}),
            message("PH_01", {"ph": 6.4}),
            message("TANK_01", {"level": 5}),
            message("SUN_01", {"lux": 78000}),
        ]
        for item in readings: self.store.ingest(item)
        result = self.agent.handle("Lập kế hoạch tưới", "Manager")
        action = result["agent_trace"][-1]["verification"]
        self.assertEqual(action["action_type"], "FIELD_TASK")
        self.assertEqual(action["payload"]["reason"], "INSUFFICIENT_WATER")

    def test_abnormal_pump(self):
        readings = [
            message("SOIL_01", {"soil_moisture": 20, "temperature": 31}),
            message("WEATHER_01", {"temperature": 35, "humidity": 48}),
            message("PUMP_01", {"flow_rate": 2.0, "power": 50}),
            message("PH_01", {"ph": 6.4}),
            message("TANK_01", {"level": 62}),
            message("SUN_01", {"lux": 78000}),
        ]
        for item in readings: self.store.ingest(item)
        result = self.agent.handle("Lập kế hoạch tưới", "Manager")
        action = result["agent_trace"][-1]["verification"]
        self.assertEqual(action["action_type"], "FIELD_TASK")
        self.assertEqual(action["payload"]["reason"], "PUMP_ABNORMAL")

    def test_evidence_required(self):
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
        observation = result["agent_trace"][0]
        evidence = observation["evidence"]
        self.assertGreater(len(evidence), 0)
        for item in evidence:
            self.assertIn("device_code", item)
            self.assertIn("device_id", item)
            self.assertIn("metric", item)
            self.assertIn("value", item)
            self.assertIn("timestamp", item)
            self.assertIn("agent", item)
            self.assertEqual(item["agent"], "Field IoT Agent")

    def test_agent_trace(self):
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
        
        self.assertIn("agent_trace", result)
        trace = result["agent_trace"]
        self.assertEqual(len(trace), 4)
        self.assertEqual(trace[0]["agent"], "Field IoT Agent")
        self.assertEqual(trace[1]["agent"], "Irrigation Planning Agent")
        self.assertEqual(trace[2]["agent"], "Resource Agent")
        self.assertEqual(trace[3]["agent"], "Farm Action Agent")

    def test_integration_scenario_a_success(self):
        readings = [
            message("SOIL_01", {"soil_moisture": 28, "temperature": 32}),
            message("WEATHER_01", {"temperature": 35, "humidity": 48}),
            message("PUMP_01", {"flow_rate": 18, "power": 430}),
            message("PH_01", {"ph": 6.4}),
            message("TANK_01", {"level": 72}),
            message("SUN_01", {"lux": 78000}),
        ]
        for item in readings: self.store.ingest(item)
        result = self.agent.handle("Lập kế hoạch tưới cho khu A và giải thích dữ liệu đã sử dụng", "Farm Manager")
        
        action = result["agent_trace"][-1]["verification"]
        self.assertEqual(action["action_type"], "IRRIGATION_PLAN")
        self.assertEqual(action["status"], "VERIFIED")
        
    def test_integration_scenario_b_stale(self):
        self.store.ingest(TelemetryMessage(device_code="SOIL_01", timestamp=time.time() - 1200, metrics={"soil_moisture": 20, "temperature": 30}))
        readings = [
            message("WEATHER_01", {"temperature": 35, "humidity": 48}),
            message("PUMP_01", {"flow_rate": 18, "power": 430}),
            message("PH_01", {"ph": 6.4}),
            message("TANK_01", {"level": 72}),
            message("SUN_01", {"lux": 78000}),
        ]
        for item in readings: self.store.ingest(item)
        result = self.agent.handle("Lập kế hoạch tưới", "Farm Manager")
        
        action = result["agent_trace"][-1]["verification"]
        self.assertEqual(action["action_type"], "FIELD_TASK")
        self.assertEqual(action["status"], "VERIFIED")
        self.assertEqual(action["payload"]["reason"], "SENSOR_DATA_STALE")

    def test_integration_scenario_c_resource_failure(self):
        readings = [
            message("SOIL_01", {"soil_moisture": 20, "temperature": 31}),
            message("WEATHER_01", {"temperature": 35, "humidity": 48}),
            message("PUMP_01", {"flow_rate": 18, "power": 430}),
            message("PH_01", {"ph": 6.4}),
            message("TANK_01", {"level": 5}),
            message("SUN_01", {"lux": 78000}),
        ]
        for item in readings: self.store.ingest(item)
        result = self.agent.handle("Lập kế hoạch tưới", "Farm Manager")
        
        action = result["agent_trace"][-1]["verification"]
        self.assertEqual(action["action_type"], "FIELD_TASK")
        self.assertEqual(action["status"], "VERIFIED")
        self.assertEqual(action["payload"]["reason"], "INSUFFICIENT_WATER")
