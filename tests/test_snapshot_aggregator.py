from __future__ import annotations

import unittest

from maple_star.backend.snapshot_aggregator import SnapshotAggregator
from maple_star.ipc.identity import MessageMeta, WorkerIdentity, WorkerRole


class SnapshotAggregatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = WorkerIdentity("session", WorkerRole.POTION, 2)
        self.aggregator = SnapshotAggregator({WorkerRole.POTION: self.identity})

    def meta(self, sequence: int, *, incarnation: int = 2) -> MessageMeta:
        return MessageMeta("session", WorkerRole.POTION, incarnation, "status", sequence, 1, 1, 1.0)

    def test_filters_stale_identity_sequence_and_duplicate_signature(self) -> None:
        self.assertTrue(self.aggregator.accept(self.meta(1), signature=(50, "ok")))
        self.assertFalse(self.aggregator.accept(self.meta(2), signature=(50, "ok")))
        self.assertFalse(self.aggregator.accept(self.meta(1), signature=(49, "old")))
        self.assertFalse(self.aggregator.accept(self.meta(3, incarnation=1), signature=(40, "stale")))
        self.assertTrue(self.aggregator.accept(self.meta(3), signature=(49, "changed")))


if __name__ == "__main__":
    unittest.main()
