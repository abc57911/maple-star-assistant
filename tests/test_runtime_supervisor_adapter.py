from __future__ import annotations

import unittest
from unittest.mock import Mock

from maple_star.backend.runtime_supervisor_adapter import SupervisedRuntimeProcessPort
from maple_star.backend.states import SupervisorState


class RuntimeSupervisorAdapterTests(unittest.TestCase):
    def test_production_adapter_reaches_ready_and_ordered_stop(self) -> None:
        coordinator = Mock()
        coordinator._guardian_process.pid = 10
        coordinator._potion_process.pid = 11
        coordinator._experience_process.pid = 12
        adapter = SupervisedRuntimeProcessPort(coordinator)

        adapter.start()
        self.assertEqual(adapter.supervisor.state, SupervisorState.READY)
        diagnostics = adapter.diagnostics_text(now=adapter.supervisor.registry.records()[0].ready_at)
        self.assertIn("guardian:pid=10,inc=1,hb=0.0s,progress=0.0s,queue=0,drop=0", diagnostics)
        adapter.stop(timeout=2.0)

        coordinator.stop.assert_called_once_with(timeout=2.0)
        self.assertEqual(adapter.supervisor.state, SupervisorState.STOPPED)


if __name__ == "__main__":
    unittest.main()
