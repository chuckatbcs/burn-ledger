"""Shared cost-spec conformance test. Identical logic in OmniBurn and Burn Ledger."""
import json
import math
import os
import unittest

try:
    from engine import cost_spec  # OmniBurn
except ImportError:  # Burn Ledger
    from app.services import cost_spec

VECTORS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cost_spec_vectors.json")


def _close(a, b):
    if isinstance(a, float) or isinstance(b, float):
        if a is None or b is None:
            return a is b
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_close(a[k], b[k]) for k in a)
    return a == b


class TestCostSpecVectors(unittest.TestCase):
    def test_vectors(self):
        with open(VECTORS) as f:
            data = json.load(f)
        for case in data["cases"]:
            got = cost_spec.pool_economics(**case["input"])
            for key, exp in case["expected"].items():
                self.assertTrue(_close(got.get(key), exp), f"{case['name']}.{key}: {got.get(key)!r} != {exp!r}")
        for w in data["weights"]:
            got = cost_spec.pool_weights(w["pool_ids"], w["explicit"])
            self.assertTrue(_close(got, w["expected"]), w["name"])

    def test_cost_per_pool_examples(self):
        # Google AI Pro $19.99 split across 2 pools, weekly ceiling binding.
        self.assertAlmostEqual(cost_spec.cost_per_pool(19.99 * 0.5, "5h + weekly"), 19.99 * 0.5 / (52 / 12), places=9)
        self.assertEqual(cost_spec.cost_per_pool(10.0, "monthly"), 10.0)
        self.assertEqual(cost_spec.cost_per_pool(0.0, "unmetered"), 0.0)

    def test_measured_beats_estimate_and_carries_range(self):
        econ = cost_spec.pool_economics(tier=2, monthly_price=19.99, pool_weight=0.5, window_type="5h + weekly",
                                        input_rate=0.75, output_rate=3.5, completed=20, weekly_delta_pct=1.0)
        self.assertEqual(econ["tasks_per_pool_evidence"], "measured")
        self.assertAlmostEqual(econ["tasks_per_pool"], 2000.0)
        self.assertLess(econ["tasks_per_pool_low"], 2000.0)
        self.assertGreater(econ["tasks_per_pool_high"], 2000.0)
        self.assertIn("measured", cost_spec.format_tasks_per_pool(econ))


if __name__ == "__main__":
    unittest.main()
