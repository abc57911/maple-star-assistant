from __future__ import annotations

import unittest

from maple_star.ipc.mailbox import BoundedFifo, LatestWinsMailbox


class IpcMailboxTests(unittest.TestCase):
    def test_latest_wins_replaces_pending_value_for_same_key(self) -> None:
        mailbox: LatestWinsMailbox[str, int] = LatestWinsMailbox(max_keys=2)

        mailbox.put("settings", 1)
        mailbox.put("settings", 2)
        mailbox.put("target", 3)

        self.assertEqual(mailbox.drain(), [("settings", 2), ("target", 3)])

    def test_latest_wins_evicts_oldest_key_at_capacity(self) -> None:
        mailbox: LatestWinsMailbox[str, int] = LatestWinsMailbox(max_keys=2)
        mailbox.put("settings", 1)
        mailbox.put("target", 2)
        mailbox.put("state", 3)

        self.assertEqual(mailbox.drain(), [("target", 2), ("state", 3)])
        self.assertEqual(mailbox.dropped_count, 1)

    def test_bounded_fifo_rejects_new_item_without_discarding_existing(self) -> None:
        fifo: BoundedFifo[int] = BoundedFifo(maxsize=2)

        self.assertTrue(fifo.put(1))
        self.assertTrue(fifo.put(2))
        self.assertFalse(fifo.put(3))

        self.assertEqual(fifo.drain(), [1, 2])
        self.assertEqual(fifo.dropped_count, 1)


if __name__ == "__main__":
    unittest.main()
