from __future__ import annotations

import unittest
from unittest.mock import patch

from maple_star.services.benchmark_environment import collect_benchmark_environment


class BenchmarkEnvironmentTests(unittest.TestCase):
    @patch("maple_star.services.benchmark_environment._active_power_plan", return_value="balanced")
    @patch("maple_star.services.benchmark_environment._git_commit", return_value="abc123")
    @patch("maple_star.services.benchmark_environment._total_ram_bytes", return_value=16_000_000_000)
    @patch("maple_star.services.benchmark_environment._cpu_name", return_value="Test CPU")
    def test_metadata_contains_required_reproducibility_fields(self, *_mocks) -> None:
        result = collect_benchmark_environment(mode="python", cache_condition="warm")

        self.assertEqual(result["commit"], "abc123")
        self.assertEqual(result["mode"], "python")
        self.assertEqual(result["cpu"], "Test CPU")
        self.assertEqual(result["ram_bytes"], 16_000_000_000)
        self.assertEqual(result["power_plan"], "balanced")
        self.assertEqual(result["cache_condition"], "warm")
        self.assertGreaterEqual(result["logical_cores"], 1)
        self.assertIn("python", result)
        self.assertIn("windows_build", result)


if __name__ == "__main__":
    unittest.main()
