import unittest

from src.mqtt_client import MQTTIngestionClient


class MQTTParserTests(unittest.TestCase):
    def test_live_batch_parses_six_devices(self):
        payload = {
            "epoch": 1786840000,
            "devices": [
                {"deviceCode": "SOIL_01", "status": "ok", "metrics": {"soil_moisture": 32}},
                {"deviceCode": "WEATHER_01", "status": "ok", "metrics": {"temperature": 31, "humidity": 60}},
                {"deviceCode": "PUMP_01", "status": "ok", "metrics": {"flow_rate": 18, "power": 430}},
                {"deviceCode": "PH_01", "status": "ok", "metrics": {"ph": 6.4}},
                {"deviceCode": "TANK_01", "status": "ok", "metrics": {"level": 72}},
                {"deviceCode": "SUN_01", "status": "ok", "metrics": {"lux": 28000}},
            ],
        }
        messages, rejected = MQTTIngestionClient.normalize_payload(payload)
        self.assertEqual(6, len(messages))
        self.assertEqual(0, rejected)

    def test_legacy_aliases_remain_supported(self):
        message = MQTTIngestionClient._normalize({"device_id": "PH_01", "timestamp": "2026-08-16T08:00:00Z", "metrics": {"ph": 6.4}})
        self.assertEqual("PH_01", message.device_code)
        self.assertIsInstance(message.timestamp, float)

    def test_invalid_record_does_not_discard_valid_batch_item(self):
        messages, rejected = MQTTIngestionClient.normalize_payload({"epoch": 1786840000, "devices": [{"deviceCode": "SOIL_01", "metrics": {"soil_moisture": 40}}, {"deviceCode": "UNKNOWN", "metrics": {"value": 1}}]})
        self.assertEqual(1, len(messages))
        self.assertEqual(1, rejected)


if __name__ == "__main__":
    unittest.main()
