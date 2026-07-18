from __future__ import annotations

import multiprocessing as mp
import pickle
import unittest

from maple_star.ipc.identity import MessageMeta, WorkerRole
from maple_star.ipc.messages import FeatureStateCommand, WorkerHeartbeat


def _round_trip_message(input_queue, output_queue) -> None:
    output_queue.put(input_queue.get(timeout=2.0))


class IpcMessageTests(unittest.TestCase):
    def test_messages_are_immutable_and_pickle_safe(self) -> None:
        meta = MessageMeta("session", WorkerRole.SUPERVISOR, 1, "command", 1, 4, 3, 5.0)
        message = FeatureStateCommand(meta, scripts_enabled=True, feature_enabled=False)

        restored = pickle.loads(pickle.dumps(message))

        self.assertEqual(restored, message)
        with self.assertRaises(AttributeError):
            restored.scripts_enabled = False

    def test_message_round_trips_through_windows_spawn(self) -> None:
        context = mp.get_context("spawn")
        input_queue = context.Queue()
        output_queue = context.Queue()
        process = context.Process(target=_round_trip_message, args=(input_queue, output_queue))
        message = WorkerHeartbeat(
            MessageMeta("session", WorkerRole.POTION, 2, "health", 1, 0, 0, 10.0),
            process_id=123,
            phase="capture",
            progress_at=9.5,
        )

        process.start()
        input_queue.put(message)
        restored = output_queue.get(timeout=5.0)
        process.join(timeout=5.0)

        self.assertEqual(process.exitcode, 0)
        self.assertEqual(restored, message)


if __name__ == "__main__":
    unittest.main()
