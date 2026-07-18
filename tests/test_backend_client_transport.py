from __future__ import annotations

import unittest

from maple_star.ipc.client_transport import ClientTransport


class BackendClientTransportTests(unittest.TestCase):
    def test_commands_are_bounded_and_enqueue_is_non_blocking(self) -> None:
        transport = ClientTransport(command_capacity=1, snapshot_keys=2, console_capacity=2)

        self.assertTrue(transport.enqueue_command("first"))
        self.assertFalse(transport.enqueue_command("overflow"))
        self.assertEqual(transport.command_dropped_count, 1)

    def test_snapshots_are_latest_wins_and_console_is_bounded(self) -> None:
        transport = ClientTransport(command_capacity=1, snapshot_keys=2, console_capacity=2)
        transport.publish_snapshot("potion", {"hp": 60})
        transport.publish_snapshot("potion", {"hp": 50})
        for message in ("one", "two", "three"):
            transport.publish_console(message)

        self.assertEqual(transport.drain_snapshots(), [("potion", {"hp": 50})])
        self.assertEqual(transport.drain_console(), ["two", "three"])
        self.assertEqual(transport.console_dropped_count, 1)


if __name__ == "__main__":
    unittest.main()
