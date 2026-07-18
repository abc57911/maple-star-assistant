from __future__ import annotations

import unittest

from maple_star.ipc.identity import MessageMeta, StreamSequencer, WorkerIdentity, WorkerRole


class IpcIdentityTests(unittest.TestCase):
    def test_sequencer_scopes_sequence_to_channel(self) -> None:
        identity = WorkerIdentity("session-a", WorkerRole.POTION, 3)
        sequencer = StreamSequencer(identity)

        first = sequencer.next("status", settings_generation=7)
        second = sequencer.next("status", settings_generation=7)
        command = sequencer.next("command", settings_generation=7)

        self.assertEqual((first.stream_sequence, second.stream_sequence), (1, 2))
        self.assertEqual(command.stream_sequence, 1)
        self.assertEqual(first.worker_incarnation, 3)

    def test_meta_rejects_stale_session_incarnation_and_sequence(self) -> None:
        current = WorkerIdentity("session-b", WorkerRole.POTION, 4)
        valid = MessageMeta("session-b", WorkerRole.POTION, 4, "status", 9, 2, 5, 10.0)

        self.assertTrue(valid.is_current(current, last_sequence=8))
        self.assertFalse(valid.is_current(current, last_sequence=9))
        self.assertFalse(valid.with_session("session-a").is_current(current, last_sequence=0))
        self.assertFalse(valid.with_incarnation(3).is_current(current, last_sequence=0))


if __name__ == "__main__":
    unittest.main()
