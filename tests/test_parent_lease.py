from __future__ import annotations

import unittest

from maple_star.backend.parent_lease import ParentLease


class ParentLeaseTests(unittest.TestCase):
    def test_any_parent_signal_loss_requests_global_stop(self) -> None:
        lease = ParentLease(heartbeat_timeout=2.0, last_heartbeat_at=10.0)

        self.assertEqual(lease.check(now=11.0, gui_pipe_alive=False, launcher_alive=True), "gui-pipe-eof")
        self.assertEqual(lease.check(now=11.0, gui_pipe_alive=True, launcher_alive=False), "launcher-exited")
        self.assertEqual(lease.check(now=13.0, gui_pipe_alive=True, launcher_alive=True), "heartbeat-timeout")
        self.assertIsNone(lease.check(now=11.0, gui_pipe_alive=True, launcher_alive=True))


if __name__ == "__main__":
    unittest.main()
