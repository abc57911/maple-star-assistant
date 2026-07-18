from __future__ import annotations

import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from maple_star.app.application import ensure_application
from maple_star.views_qt.backend_threads import BackendReceiverThread


class QtBackendThreadTests(unittest.TestCase):
    def test_receiver_wakes_and_joins_without_terminate(self) -> None:
        app = ensure_application([])
        batches: list[list[object]] = []
        thread = BackendReceiverThread(poll=lambda: ["snapshot"])
        thread.batch_ready.connect(batches.append)
        thread.start()

        deadline = time.monotonic() + 1.0
        while not batches and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        thread.close(timeout_ms=1000)

        self.assertEqual(batches[0], ["snapshot"])
        self.assertFalse(thread.isRunning())


if __name__ == "__main__":
    unittest.main()
