from __future__ import annotations

import multiprocessing as mp
import unittest

from maple_star.app.child_roles import ChildRoleBootstrap, probe_child_imports
from maple_star.ipc.identity import WorkerRole


class ChildImportIsolationTests(unittest.TestCase):
    def test_spawned_child_does_not_load_gui_or_heavy_runtime_packages(self) -> None:
        context = mp.get_context("spawn")
        result_queue = context.Queue()
        bootstrap = ChildRoleBootstrap(
            session_epoch="isolation",
            role=WorkerRole.SUPERVISOR,
            incarnation=1,
            parent_pid=1234,
        )
        process = context.Process(target=probe_child_imports, args=(bootstrap, result_queue))

        process.start()
        process.join(timeout=10.0)

        self.assertEqual(process.exitcode, 0)
        result = result_queue.get(timeout=1.0)
        self.assertEqual(result["loaded_forbidden_modules"], [])
        self.assertEqual(result["role"], "supervisor")


if __name__ == "__main__":
    unittest.main()
