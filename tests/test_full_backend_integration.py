from __future__ import annotations

import queue
import unittest

from maple_star.adapters import win_input
from maple_star.controllers.runtime_child_entrypoints import run_control_runtime_with_guardian
from maple_star.models.settings import AutoPotionSettings
from maple_star.services.runtime_api import Shutdown
from maple_star.services.runtime_processes import RuntimeProcessCoordinator
from maple_star.workers.input_guardian_process import run_input_guardian_process


def _idle_domain_worker(
    command_queue,
    _status_queue,
    _settings,
    _target,
    _guardian_queue=None,
    _guardian_generation=None,
) -> None:
    while True:
        try:
            command = command_queue.get(timeout=1.0)
        except queue.Empty:
            continue
        if isinstance(command, Shutdown):
            return


class FullBackendIntegrationTests(unittest.TestCase):
    def test_guardian_starts_first_and_stops_after_domain_workers(self) -> None:
        runtime = RuntimeProcessCoordinator(
            AutoPotionSettings(),
            potion_worker_target=_idle_domain_worker,
            experience_worker_target=_idle_domain_worker,
            guardian_worker_target=run_input_guardian_process,
            guarded_control_target=run_control_runtime_with_guardian,
        )

        runtime.start()
        self.assertTrue(runtime._guardian_process.is_alive())
        self.assertTrue(runtime.potion_alive())
        self.assertTrue(runtime.experience_alive())
        self.assertIsNotNone(win_input._MUTATION_PROXY)

        self.assertEqual(runtime.safety_fence(), 1)
        self.assertEqual(runtime.rearm_input(), 1)

        runtime.stop(timeout=2.0)

        self.assertFalse(runtime._guardian_process.is_alive())
        self.assertFalse(runtime.potion_alive())
        self.assertFalse(runtime.experience_alive())
        self.assertIsNone(win_input._MUTATION_PROXY)


if __name__ == "__main__":
    unittest.main()
