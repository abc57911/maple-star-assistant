from __future__ import annotations

import unittest

from maple_star.workers.potion_vision import PotionVisionRuntime


class PotionWorkerProcessTests(unittest.TestCase):
    def test_heartbeat_and_progress_are_independent_during_long_capture(self) -> None:
        runtime = PotionVisionRuntime(session_epoch="session", heartbeat_interval=0.5)
        runtime.begin_phase("capture", now=1.0)

        heartbeat = runtime.heartbeat(now=2.5, process_id=10)

        self.assertEqual(heartbeat.phase, "capture")
        self.assertEqual(heartbeat.progress_at, 1.0)
        self.assertEqual(runtime.progress_at, 1.0)
        runtime.mark_progress(now=3.0)
        self.assertEqual(runtime.progress_at, 3.0)


if __name__ == "__main__":
    unittest.main()
