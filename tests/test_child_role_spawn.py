from __future__ import annotations

import multiprocessing as mp
import unittest

from maple_star.app.child_roles import ChildRoleBootstrap, run_noop_child
from maple_star.ipc.identity import WorkerRole


class ChildRoleSpawnTests(unittest.TestCase):
    def test_top_level_child_target_round_trips_bootstrap(self) -> None:
        context = mp.get_context("spawn")
        result_queue = context.Queue()
        bootstrap = ChildRoleBootstrap(
            session_epoch="session-1",
            role=WorkerRole.POTION,
            incarnation=3,
            parent_pid=1234,
        )
        process = context.Process(target=run_noop_child, args=(bootstrap, result_queue))
        process.daemon = False

        process.start()
        process.join(timeout=10.0)

        self.assertEqual(process.exitcode, 0)
        self.assertFalse(process.is_alive())
        self.assertEqual(
            result_queue.get(timeout=1.0),
            {
                "session_epoch": "session-1",
                "role": "potion",
                "incarnation": 3,
                "parent_pid": 1234,
            },
        )


if __name__ == "__main__":
    unittest.main()
