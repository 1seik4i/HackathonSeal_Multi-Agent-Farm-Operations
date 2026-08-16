import time
import unittest

from src.data_processor import IoTDataProcessor


class IoTDataProcessorTests(unittest.TestCase):
    def setUp(self):
        self.processor = IoTDataProcessor(stale_after_seconds=60)

    def test_freshness_uses_sixty_second_window(self):
        now = time.time()
        self.assertEqual("FRESH", self.processor.compute_freshness(now - 59, now=now))
        self.assertEqual("STALE", self.processor.compute_freshness(now - 61, now=now))

    def test_out_of_range_value_is_preserved_and_flagged(self):
        result = self.processor.process({"device_code": "SOIL_01", "timestamp": time.time(), "metrics": {"soil_moisture": 120}})
        self.assertEqual(120, result["metrics"]["soil_moisture"])
        self.assertFalse(result["quality"]["valid"])
        self.assertEqual("soil_moisture", result["quality"]["out_of_range"][0]["metric"])

    def test_invalid_device_is_rejected(self):
        with self.assertRaises(ValueError):
            self.processor.process({"device_code": "UNKNOWN", "metrics": {"value": 1}})


if __name__ == "__main__":
    unittest.main()
