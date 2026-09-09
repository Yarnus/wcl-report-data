import unittest

from tools.benchmark import measure


class BenchmarkTests(unittest.TestCase):
    def test_offline_workflows_measure_acquisition_and_real_local_validation(self):
        expected = {
            "first_inspect": (3, 0, 0),
            "cold_prepare": (5, 0, 0),
            "cached_prepare": (2, 0, 1),
            "mechanics_followups": (9, 0, 0),
            "triage": (8, 0, 0),
            "personal_existing": (0, 0, 39),
            "multi_boss_guide": (29, 7, 24),
        }
        for name, (wcl, wago, passes) in expected.items():
            with self.subTest(scenario=name):
                result = measure(name)
                metrics = result["diagnostics"]
                network = metrics["network"]
                self.assertEqual(sum(value["attempts"] for key, value in network.items() if not key.startswith("Wago")), wcl)
                self.assertEqual(sum(value["attempts"] for key, value in network.items() if key.startswith("Wago")), wago)
                self.assertEqual(metrics["counters"].get("canonical_event_passes", 0), passes)
                if name == "triage":
                    for operation in ("OAuth", "RateLimit", "ReportIndex"):
                        self.assertEqual(network[operation]["attempts"], 1)
                    self.assertEqual(network["ReportRevision"]["attempts"], 3)
                self.assertGreater(result["wall_seconds"], 0)
                self.assertGreater(result["cpu_seconds"], 0)
