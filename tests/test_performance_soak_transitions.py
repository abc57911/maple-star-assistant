from __future__ import annotations

import unittest

from tools.benchmark_control_timing import run_benchmark


class PerformanceSoakTransitionTests(unittest.TestCase):
    def test_scaled_soak_exercises_all_transition_types(self) -> None:
        result = run_benchmark(3.0, 0.01, exercise_transitions=True, transition_scale=0.001)

        self.assertGreaterEqual(result["focus_transition_count"], 1)
        self.assertGreaterEqual(result["settings_transition_count"], 1)
        self.assertEqual(result["observer_delay_count"], 1)
        self.assertGreater(result["sample_count"], 0)


if __name__ == "__main__":
    unittest.main()
