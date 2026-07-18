from __future__ import annotations

import unittest
from unittest.mock import Mock

from maple_star.backend.runtime_supervisor_adapter import SupervisedRuntimeProcessPort
from maple_star.backend.states import SupervisorState


class BackendChaosTests(unittest.TestCase):
    def _ready_adapter(self) -> tuple[SupervisedRuntimeProcessPort, Mock]:
        coordinator = Mock()
        coordinator._guardian_process.pid = 10
        coordinator._potion_process.pid = 11
        coordinator._experience_process.pid = 12
        adapter = SupervisedRuntimeProcessPort(coordinator)
        adapter.start()
        return adapter, coordinator

    def test_domain_exit_degrades_but_guardian_exit_fences_and_fails(self) -> None:
        adapter, coordinator = self._ready_adapter()
        coordinator.potion_alive.return_value = False
        self.assertFalse(adapter.potion_alive())
        self.assertEqual(adapter.supervisor.state, SupervisorState.DEGRADED)

        coordinator.guardian_alive.return_value = False
        self.assertFalse(adapter.guardian_alive())
        self.assertEqual(adapter.supervisor.state, SupervisorState.FAILED)
        coordinator.safety_fence.assert_called()


if __name__ == "__main__":
    unittest.main()
